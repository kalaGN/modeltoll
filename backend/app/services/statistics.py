"""租户范围下的调用与费用查询与聚合（设计 §9）。

所有 SQL 都带认证用户范围；Key ID 与请求 ID 只是资源定位符，不构成权限。
汇总与明细用同一 [from, to) 半开区间，便于对账（验收 A08）。
"""

from __future__ import annotations

import base64
import datetime
from decimal import Decimal
from typing import Any

from app.core import config, security
from app.db import session
from app.services import api_keys, billing
from app.services.accounts import utc_now


class StatsError(Exception):
    status_code = 400
    code = "invalid_range"
    message = "时间范围无效"


def parse_range(date_from: str, date_to: str) -> tuple[datetime.datetime, datetime.datetime]:
    """接受 YYYY-MM-DD 或 ISO 时间；带偏移的按 UTC 归一，返回 naive UTC。

    只给日期时：from 取当日 00:00，to 取次日 00:00；`to` 始终是开区间上界。
    缺省窗口是采用值，统计时区与边界仍待产品确认（需求 §9）。
    """
    now = utc_now()
    start = _parse_bound(date_from, upper=False) or now - datetime.timedelta(
        days=config.STATS_DEFAULT_DAYS
    )
    end = _parse_bound(date_to, upper=True) or now
    if end <= start:
        raise StatsError()
    return start, end


def _parse_bound(raw: str, *, upper: bool) -> datetime.datetime | None:
    text = raw.strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            day_start = datetime.datetime.combine(
                datetime.date.fromisoformat(text), datetime.time.min
            )
            return day_start + datetime.timedelta(days=1) if upper else day_start
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        raise StatsError() from None
    if parsed.tzinfo is not None:
        # 带偏移的入参先换算到 UTC 再去掉 tzinfo：与 naive UTC 列直接比较，
        # 也避免与缺省边界（naive）比较时抛 TypeError。
        parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return parsed


def encode_cursor(started_at: datetime.datetime, row_id: str) -> str:
    raw = f"{started_at.strftime('%Y-%m-%d %H:%M:%S.%f')}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime.datetime, str] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        stamp, row_id = raw.split("|", 1)
        return datetime.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S.%f"), row_id
    except (ValueError, UnicodeDecodeError):
        raise StatsError() from None


def page_size(limit: int) -> int:
    return max(1, min(limit or config.PAGE_SIZE_DEFAULT, config.PAGE_SIZE_MAX))


def _filters(
    user_id: str, start: datetime.datetime, end: datetime.datetime, api_key_id: str, endpoint: str
) -> tuple[list[str], list[Any]]:
    where = ["c.user_id = %s", "c.started_at >= %s", "c.started_at < %s"]
    args: list[Any] = [user_id, start, end]
    if api_key_id:
        where.append("c.api_key_id = %s")
        args.append(api_key_id)
    if endpoint:
        where.append("c.endpoint = %s")
        args.append(endpoint)
    return where, args


def usage_summary(
    user_id: str,
    start: datetime.datetime,
    end: datetime.datetime,
    api_key_id: str = "",
    endpoint: str = "",
) -> dict[str, Any]:
    where, args = _filters(user_id, start, end, api_key_id, endpoint)
    with session.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS total,"
            f" SUM(c.status = 'succeeded') AS succeeded,"
            f" SUM(c.status IN ('failed', 'interrupted')) AS failed,"
            f" SUM(c.status IN ('accepted', 'running')) AS in_progress,"
            f" COALESCE(SUM(c.input_tokens), 0) AS input_tokens,"
            f" COALESCE(SUM(c.output_tokens), 0) AS output_tokens"
            f" FROM api_calls c WHERE {' AND '.join(where)}",
            args,
        )
        calls = cur.fetchone()
        cur.execute(
            f"SELECT COUNT(*) AS billable_calls, COALESCE(SUM(h.billable_input_tokens), 0)"
            f" AS billable_tokens, COALESCE(SUM(h.amount_yuan), 0) AS amount"
            f" FROM usage_charges h JOIN api_calls c ON c.id = h.call_id"
            f" WHERE {' AND '.join(where)}",
            args,
        )
        charged = cur.fetchone()
        cur.execute(
            f"SELECT COUNT(*) AS pending FROM api_calls c"
            f" WHERE {' AND '.join(where)} AND c.billing_status = 'pending'",
            args,
        )
        pending = cur.fetchone()
    return {
        "calls_total": int(calls["total"] or 0),
        "calls_succeeded": int(calls["succeeded"] or 0),
        "calls_failed": int(calls["failed"] or 0),
        "calls_in_progress": int(calls["in_progress"] or 0),
        "input_tokens": int(calls["input_tokens"] or 0),
        "output_tokens": int(calls["output_tokens"] or 0),
        "billable_tokens": int(charged["billable_tokens"] or 0),
        "charged_amount_yuan": str(Decimal(str(charged["amount"] or 0))),
        "billing_pending_count": int(pending["pending"] or 0),
    }


def usage_calls(
    user_id: str,
    start: datetime.datetime,
    end: datetime.datetime,
    api_key_id: str = "",
    endpoint: str = "",
    limit: int = 0,
    cursor: str = "",
) -> dict[str, Any]:
    size = page_size(limit)
    where, args = _filters(user_id, start, end, api_key_id, endpoint)
    after = decode_cursor(cursor)
    if after:
        where.append("(c.started_at, c.id) < (%s, %s)")
        args.extend([after[0], after[1]])
    with session.cursor() as cur:
        cur.execute(
            "SELECT c.id, c.endpoint, c.model, c.status, c.http_status, c.error_code,"
            " c.started_at, c.duration_ms, c.input_tokens, c.output_tokens,"
            " c.billing_status, c.billing_reason, k.display_prefix, k.last_four,"
            " p.version AS pricing_version"
            " FROM api_calls c"
            " JOIN api_keys k ON k.id = c.api_key_id"
            " JOIN pricing_rules p ON p.id = c.pricing_rule_id"
            f" WHERE {' AND '.join(where)}"
            " ORDER BY c.started_at DESC, c.id DESC LIMIT %s",
            (*args, size + 1),
        )
        rows = cur.fetchall()
    has_more = len(rows) > size
    rows = rows[:size]
    return {
        "items": [_call_item(row) for row in rows],
        "next_cursor": encode_cursor(rows[-1]["started_at"], rows[-1]["id"]) if rows else "",
        "has_more": has_more,
    }


def _call_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": row["id"],
        "api_key": security_display(row),
        "endpoint": row["endpoint"],
        "model": row["model"],
        "started_at": api_keys.iso_utc(row["started_at"]),
        "status": row["status"],
        "http_status": row["http_status"],
        "error_code": row["error_code"],
        "duration_ms": row["duration_ms"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "billing_status": row["billing_status"],
        "pricing_version": row["pricing_version"],
    }


def security_display(row: dict[str, Any]) -> str:
    return security.masked_key(row["display_prefix"], row["last_four"])


def billing_summary(
    user_id: str,
    start: datetime.datetime,
    end: datetime.datetime,
    api_key_id: str = "",
    endpoint: str = "",
) -> dict[str, Any]:
    summary = usage_summary(user_id, start, end, api_key_id, endpoint)
    where, args = _filters(user_id, start, end, api_key_id, endpoint)
    with session.cursor() as cur:
        cur.execute(
            f"SELECT COALESCE(SUM(h.amount_yuan), 0) AS amount,"
            f" COALESCE(SUM(h.billable_input_tokens), 0) AS tokens,"
            f" COUNT(*) AS charges"
            f" FROM usage_charges h JOIN api_calls c ON c.id = h.call_id"
            f" WHERE {' AND '.join(where)}",
            args,
        )
        row = cur.fetchone()
    return {
        "charged_amount_yuan": str(Decimal(str(row["amount"] or 0))),
        "billable_tokens": int(row["tokens"] or 0),
        "charge_count": int(row["charges"] or 0),
        "billing_pending_count": summary["billing_pending_count"],
        "calls_total": summary["calls_total"],
    }


def billing_charges(
    user_id: str,
    start: datetime.datetime,
    end: datetime.datetime,
    api_key_id: str = "",
    endpoint: str = "",
    limit: int = 0,
    cursor: str = "",
) -> dict[str, Any]:
    size = page_size(limit)
    where, args = _filters(user_id, start, end, api_key_id, endpoint)
    after = decode_cursor(cursor)
    if after:
        where.append("(c.started_at, c.id) < (%s, %s)")
        args.extend([after[0], after[1]])
    with session.cursor() as cur:
        cur.execute(
            "SELECT c.id AS call_id, c.started_at, k.display_prefix, k.last_four,"
            " h.billable_input_tokens, h.unit_tokens, h.unit_price_yuan, h.amount_yuan,"
            " h.currency, p.version AS pricing_version"
            " FROM usage_charges h"
            " JOIN api_calls c ON c.id = h.call_id"
            " JOIN api_keys k ON k.id = c.api_key_id"
            " JOIN pricing_rules p ON p.id = h.pricing_rule_id"
            f" WHERE {' AND '.join(where)}"
            " ORDER BY c.started_at DESC, c.id DESC LIMIT %s",
            (*args, size + 1),
        )
        rows = cur.fetchall()
    has_more = len(rows) > size
    rows = rows[:size]
    return {
        "items": [
            {
                "request_id": row["call_id"],
                "api_key": security_display(row),
                "started_at": api_keys.iso_utc(row["started_at"]),
                "billable_tokens": int(row["billable_input_tokens"]),
                "unit_tokens": int(row["unit_tokens"]),
                "unit_price_yuan": str(Decimal(str(row["unit_price_yuan"]))),
                "amount_yuan": str(Decimal(str(row["amount_yuan"]))),
                "currency": row["currency"],
                "pricing_version": row["pricing_version"],
            }
            for row in rows
        ],
        "next_cursor": encode_cursor(rows[-1]["started_at"], rows[-1]["call_id"]) if rows else "",
        "has_more": has_more,
    }


def daily_series(
    user_id: str,
    start: datetime.datetime,
    end: datetime.datetime,
    api_key_id: str = "",
    endpoint: str = "",
) -> list[dict[str, Any]]:
    """按 UTC 日期分桶的趋势，只服务图表展示；账务事实仍是明细与费用行。"""
    where, args = _filters(user_id, start, end, api_key_id, endpoint)
    with session.cursor() as cur:
        cur.execute(
            "SELECT DATE(c.started_at) AS day,"
            " SUM(c.status = 'succeeded') AS succeeded,"
            " SUM(c.status IN ('failed', 'interrupted')) AS failed,"
            " COALESCE(SUM(c.input_tokens), 0) AS tokens,"
            " COALESCE(SUM(h.amount_yuan), 0) AS amount"
            " FROM api_calls c LEFT JOIN usage_charges h ON h.call_id = c.id"
            f" WHERE {' AND '.join(where)}"
            " GROUP BY DATE(c.started_at) ORDER BY day",
            args,
        )
        rows = cur.fetchall()
    return [
        {
            "date": row["day"].isoformat() if hasattr(row["day"], "isoformat") else str(row["day"]),
            "succeeded": int(row["succeeded"] or 0),
            "failed": int(row["failed"] or 0),
            "input_tokens": int(row["tokens"] or 0),
            "amount_yuan": str(Decimal(str(row["amount"] or 0))),
        }
        for row in rows
    ]


def current_price(model: str) -> dict[str, Any]:
    try:
        return billing.current_rule(model).public
    except billing.NoPricingRule:
        return {}

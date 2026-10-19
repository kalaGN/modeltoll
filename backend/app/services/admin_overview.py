"""Administrator-wide aggregates; independent from user-scoped statistics."""
import datetime
from decimal import Decimal

from app.core.time import iso_utc
from app.db import session


def overview(start: datetime.datetime, end: datetime.datetime) -> dict:
    # 一个只读事务确保各指标同一快照；费用表 call_id 唯一，JOIN 不放大调用数。
    with session.transaction() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM users")
        users = int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(*) AS n FROM api_keys k JOIN users u ON u.id = k.user_id"
                    " WHERE k.revoked_at IS NULL AND k.deleted_at IS NULL AND u.status = 'active'")
        keys = int(cur.fetchone()["n"])
        cur.execute("SELECT DATE(c.started_at) AS day, COUNT(*) AS calls,"
                    " COALESCE(SUM(h.amount_yuan), 0) AS amount FROM api_calls c"
                    " LEFT JOIN usage_charges h ON h.call_id = c.id"
                    " WHERE c.started_at >= %s AND c.started_at < %s"
                    " GROUP BY DATE(c.started_at) ORDER BY day", (start, end))
        rows = cur.fetchall()
    series = [{"date": row["day"].isoformat(), "calls": int(row["calls"]),
               "amount_yuan": str(Decimal(row["amount"]))} for row in rows]
    return {"range": {"from": iso_utc(start), "to": iso_utc(end)},
            "totals": {"users": users, "active_keys": keys,
                       "calls": sum(row["calls"] for row in series),
                       "amount_yuan": str(sum((Decimal(row["amount_yuan"]) for row in series), Decimal(0))),
                       "currency": "CNY"}, "series": series}

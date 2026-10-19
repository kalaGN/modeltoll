"""Administrator-wide aggregates; independent from user-scoped statistics."""
import datetime
from decimal import Decimal

from app.core.time import iso_utc
from app.db import session
from app.repositories import statistics as repository


def overview(start: datetime.datetime, end: datetime.datetime) -> dict:
    # 一个只读事务确保各指标同一快照；费用表 call_id 唯一，JOIN 不放大调用数。
    with session.read_session() as db:
        users, keys, rows = repository.platform_overview(db, start, end)
    series = [{"date": row["day"].isoformat(), "calls": int(row["calls"]),
               "amount_yuan": str(Decimal(row["amount"]))} for row in rows]
    return {"range": {"from": iso_utc(start), "to": iso_utc(end)},
            "totals": {"users": users, "active_keys": keys,
                       "calls": sum(row["calls"] for row in series),
                       "amount_yuan": str(sum((Decimal(row["amount_yuan"]) for row in series), Decimal(0))),
                       "currency": "CNY"}, "series": series}

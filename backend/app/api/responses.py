"""Explicit flat success payloads for management APIs, not global wrapping."""
import datetime
from typing import Any

from app.core.time import iso_utc


def success(*, code: str = "ok", **payload: Any) -> dict[str, Any]:
    """Build content only; callers retain status codes, headers and cookies."""
    return {"code": code, **payload}


def utc_range(start: datetime.datetime, end: datetime.datetime) -> dict[str, str | None]:
    """Format bounds already normalized by parse_range, retaining second precision."""
    return {"from": iso_utc(start), "to": iso_utc(end), "timezone": "UTC"}

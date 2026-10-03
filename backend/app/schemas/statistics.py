"""统计接口查询参数契约；时间按 UTC 解释，分页有上限。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatsQuery:
    date_from: str = ""
    date_to: str = ""
    api_key_id: str = ""
    endpoint: str = ""
    limit: int = 0
    cursor: str = ""

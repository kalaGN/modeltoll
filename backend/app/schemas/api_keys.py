"""API Key 管理接口契约。完整秘密只出现在创建响应中一次。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RevokeRequest(BaseModel):
    """撤销只需要路径中的 Key ID；保留空模型以便后续补充确认字段。"""

    confirm: bool = Field(default=False)

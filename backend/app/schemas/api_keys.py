"""API Key 管理接口契约。完整秘密只出现在创建响应中一次。"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

NAME_MAX_LENGTH = 60


class CreateKeyRequest(BaseModel):
    """名称可选，仅用于展示与识别；空白一律归一为空串（未命名）。"""

    name: str = Field(default="", max_length=NAME_MAX_LENGTH)

    @model_validator(mode="after")
    def normalize_name(self):
        self.name = self.name.strip()
        if len(self.name) > NAME_MAX_LENGTH:
            raise ValueError(f"name 不能超过 {NAME_MAX_LENGTH} 个字符")
        return self


class RevokeRequest(BaseModel):
    """撤销只需要路径中的 Key ID；保留空模型以便后续补充确认字段。"""

    confirm: bool = Field(default=False)

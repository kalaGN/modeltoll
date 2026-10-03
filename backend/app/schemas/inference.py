"""推理接口请求契约，字段与语义保持迁移前一致。"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class CustomerServiceRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.message.strip():
            raise ValueError("message 不能为空白")
        return self


class Question(BaseModel):
    type: Literal["choice", "score", "noul"]
    instructions: str = Field(min_length=1, max_length=2000)
    criteria: dict[str, str] | list[str] | None = None

    @model_validator(mode="after")
    def validate_criteria(self):
        if not self.instructions.strip():
            raise ValueError("instructions 不能为空白")
        if self.type == "choice":
            if not isinstance(self.criteria, dict) or not 2 <= len(self.criteria) <= 20:
                raise ValueError("choice.criteria 必须是包含 2 到 20 项的对象")
        elif self.type == "score":
            if not isinstance(self.criteria, list) or not 2 <= len(self.criteria) <= 20:
                raise ValueError("score.criteria 必须是包含 2 到 20 项的列表")
        elif self.criteria is not None:
            if not isinstance(self.criteria, dict) or not set(self.criteria) <= {"true", "false"}:
                raise ValueError("noul.criteria 只支持 true/false 描述")
        if self.criteria is not None:
            values = self.criteria.values() if isinstance(self.criteria, dict) else self.criteria
            if any(not v.strip() or len(v) > 1000 for v in values):
                raise ValueError("criteria 描述必须非空，且不超过 1000 字符")
        return self


class PredictRequest(BaseModel):
    state: str | dict[str, Any] | list[Any]
    questions: dict[str, Question] = Field(min_length=1, max_length=20)
    lang: str = Field(default="zh", min_length=2, max_length=20)

    @model_validator(mode="after")
    def limit_state(self):
        if len(json.dumps(self.state, ensure_ascii=False)) > 16000:
            raise ValueError("state 不能超过 16000 字符")
        return self

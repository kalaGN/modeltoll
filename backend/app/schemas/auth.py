"""注册/登录/会话请求契约。"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.core import config
from app.core import validation


class CredentialsRequest(BaseModel):
    email: str = Field(min_length=3, max_length=config.EMAIL_MAX)
    password: str = Field(min_length=config.PASSWORD_MIN, max_length=config.PASSWORD_MAX)

    @model_validator(mode="after")
    def normalize_email(self):
        normalized = validation.normalize_email(self.email)
        if not validation.valid_email_shape(normalized):
            raise ValueError("邮箱格式不正确")
        self.email = normalized
        return self

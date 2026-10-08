"""文字、单模型、非流式契约；未知字段显式拒绝。"""
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ConnectionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    base_url: str = Field(min_length=1, max_length=512)
    model: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_./:-]+$')
    timeout_seconds: int = Field(default=120, ge=1, le=300, strict=True)
    enabled: bool = False

    @field_validator('base_url')
    @classmethod
    def valid_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if (parts.scheme not in {'http', 'https'} or not parts.hostname or
                parts.username is not None or parts.password is not None or parts.query or parts.fragment or
                parts.path.rstrip('/') != '/v1' or any(ord(c) < 33 for c in value) or '\\' in value):
            raise ValueError('Base URL 必须是 http(s)://主机[:端口]/v1，不含凭据或查询参数')
        if parts.port is not None and not 1 <= parts.port <= 65535:
            raise ValueError('端口无效')
        return value.rstrip('/')


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['system', 'user', 'assistant']
    content: str = Field(min_length=1, max_length=32000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model: str = Field(min_length=1, max_length=64)
    messages: list[ChatMessage] = Field(min_length=1, max_length=64)
    stream: Literal[False] = False
    max_tokens: int | None = Field(default=None, ge=1, le=32768, strict=True)
    temperature: float | None = Field(default=None, ge=0, le=2, allow_inf_nan=False)
    top_p: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)

    @model_validator(mode='after')
    def total_text_limit(self):
        if sum(len(item.content) for item in self.messages) > 64000:
            raise ValueError('消息总长度不能超过 64000 字符')
        return self

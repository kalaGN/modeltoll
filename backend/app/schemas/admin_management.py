"""Strict request contracts for administrator account/key operations."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=200, strict=True)


class UserStatusRequest(ReasonRequest):
    status: Literal['active', 'disabled']

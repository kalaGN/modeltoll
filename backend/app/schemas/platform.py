"""Platform branding settings contract; HTTP body limits stay in the route."""
from pydantic import BaseModel, ConfigDict, Field


class SettingsRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=200)
    logo_data_url: str | None = Field(default=None, max_length=2800000)

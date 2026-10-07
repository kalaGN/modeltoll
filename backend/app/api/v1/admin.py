"""管理员总览、品牌配置与公开品牌展示。"""
from __future__ import annotations

import datetime
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.api import dependencies
from app.services import accounts, platform, statistics

router = APIRouter(tags=["platform"])
MAX_BODY = 3 * 1024 * 1024


class SettingsRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=200)
    logo_data_url: str | None = Field(default=None, max_length=2800000)


@router.get("/v1/platform/branding")
def branding():
    return {"code": "ok", "branding": platform.branding()}


@router.get("/v1/platform/logo")
def logo():
    image = platform.logo()
    if image is None:
        raise HTTPException(status_code=404, detail="未设置 Logo")
    return Response(image, media_type="image/png",
                    headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"})


@router.get("/v1/admin/overview")
def overview(
    user: accounts.User = Depends(dependencies.require_admin),
    date_from: str = Query(default="", alias="from", max_length=64),
    date_to: str = Query(default="", alias="to", max_length=64),
):
    try:
        start, end = statistics.parse_range(date_from, date_to)
    except statistics.StatsError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message}) from None
    if end - start > datetime.timedelta(days=366):
        raise HTTPException(status_code=400, detail={"code": "invalid_range", "message": "时间范围不能超过 366 天"})
    return {"code": "ok", **platform.overview(start, end)}


@router.put("/v1/admin/settings", openapi_extra={
    "requestBody": {"required": True, "content": {
        "application/json": {"schema": SettingsRequest.model_json_schema()}
    }}
})
async def settings(
    request: Request,
    user: accounts.User = Depends(dependencies.require_admin),
    x_csrf_token: str = Header(default=""),
):
    dependencies.require_csrf(request, x_csrf_token)
    # 在读取整个 JSON 前限制流大小，避免无 Content-Length 或伪造长度绕过。
    parts = bytearray()
    async for chunk in request.stream():
        if len(parts) + len(chunk) > MAX_BODY:
            raise HTTPException(status_code=413, detail={"code": "body_too_large", "message": "配置请求过大"})
        parts.extend(chunk)
    try:
        body = SettingsRequest.model_validate(json.loads(parts))
    except ValueError:
        # 不回显图片、完整请求或 Pydantic input 内容。
        raise HTTPException(status_code=422, detail="平台名称、简介或 Logo 输入无效") from None
    # 解码图片及同步数据库操作放在线程池，避免阻塞 ASGI 事件循环。
    try:
        saved = await run_in_threadpool(platform.save_settings, body.name, body.description, body.logo_data_url)
    except platform.InvalidLogo as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"code": "ok", "branding": saved}

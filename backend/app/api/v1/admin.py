"""管理员总览与品牌配置写入；公开品牌在 platform 路由。"""
from __future__ import annotations

import datetime
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from app.api import dependencies
from app.api.errors import error_content, http_error
from app.api.request_body import read_limited_body
from app.api.responses import success
from app.schemas.platform import SettingsRequest
from app.services import accounts, admin_overview, branding, statistics

router = APIRouter(tags=["platform"])
MAX_BODY = 3 * 1024 * 1024


@router.get("/v1/admin/overview")
def overview(
    user: accounts.User = Depends(dependencies.require_admin),
    date_from: str = Query(default="", alias="from", max_length=64),
    date_to: str = Query(default="", alias="to", max_length=64),
):
    try:
        start, end = statistics.parse_range(date_from, date_to)
    except statistics.StatsError as exc:
        raise http_error(400, exc.code, exc.message) from None
    if end - start > datetime.timedelta(days=366):
        raise http_error(400, "invalid_range", "时间范围不能超过 366 天")
    return success(**admin_overview.overview(start, end))


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
    parts = await read_limited_body(
        request, MAX_BODY, detail=error_content("body_too_large", "配置请求过大"),
    )
    try:
        body = SettingsRequest.model_validate(json.loads(parts))
    except ValueError:
        # 不回显图片、完整请求或 Pydantic input 内容。
        raise HTTPException(status_code=422, detail="平台名称、简介或 Logo 输入无效") from None
    # 解码图片及同步数据库操作放在线程池，避免阻塞 ASGI 事件循环。
    try:
        saved = await run_in_threadpool(branding.save_settings, body.name, body.description, body.logo_data_url)
    except branding.InvalidLogo as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return success(branding=saved)

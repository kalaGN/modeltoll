"""会话、API Key 与 CSRF 请求依赖。归属只来自服务端凭据，不信任客户端提交。"""

from __future__ import annotations

from contextlib import contextmanager

from fastapi import Depends, Request

from app.api.errors import http_error
from app.core import config, security
from app.services import accounts, api_keys, request_limits


@contextmanager
def admit_inference(principal: api_keys.Principal):
    """从准入到结算持有用户名额，限流错误只在 HTTP 边界转换。"""
    try:
        with request_limits.admit(principal.user_id):
            yield
    except request_limits.RateLimitError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        raise http_error(exc.status_code, exc.code, exc.message, headers=headers) from None


def session_token(request: Request) -> str:
    return request.cookies.get(config.SESSION_COOKIE, "")


def current_user(request: Request) -> accounts.User | None:
    return accounts.current_user(session_token(request))


def require_user(request: Request) -> accounts.User:
    user = current_user(request)
    if user is None:
        raise http_error(401, "unauthenticated", "登录状态无效或已过期")
    return user


def require_api_key(request: Request) -> api_keys.Principal:
    """推理接口只接受 Bearer API Key；登录会话不能代替 Key（设计 §13）。"""
    try:
        return api_keys.authenticate(request.headers.get("Authorization", ""))
    except api_keys.ApiKeyError as exc:
        raise http_error(exc.status_code, exc.code, exc.message) from None


def require_csrf(request: Request, header_value: str) -> None:
    """双重提交 Cookie：会话建立前的写操作也要求，避免会话固定与跨站表单提交。"""
    if not security.csrf_matches(request.cookies.get(config.CSRF_COOKIE, ""), header_value):
        raise http_error(403, "csrf_failed", "缺少或错误的 CSRF 令牌")


def issue_csrf_cookie(response, token: str) -> None:
    response.set_cookie(
        key=config.CSRF_COOKIE,
        value=token,
        path="/",
        httponly=False,  # 前端脚本需读取并回填到请求头
        samesite="lax",
        secure=False,
    )


def require_admin(user: accounts.User = Depends(require_user)) -> accounts.User:
    if not user.is_admin:
        raise http_error(403, "admin_required", "需要管理员权限")
    return user

"""登录、注册、退出与当前用户。契约见 docs/20261002-Laya平台-任务.md。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api import dependencies
from app.api.errors import error_content
from app.api.responses import success
from app.core import config, security
from app.schemas.auth import CredentialsRequest
from app.services.access import accounts

logger = logging.getLogger("laya.api.auth")
router = APIRouter(prefix="/v1/auth", tags=["auth"])


def auth_failed(exc: accounts.AuthError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code, content=error_content(exc.code, exc.message)
    )


def set_session_cookie(response: JSONResponse, token: str) -> JSONResponse:
    response.set_cookie(
        key=config.SESSION_COOKIE,
        value=token,
        max_age=config.SESSION_TTL_MINUTES * 60,
        path="/",
        httponly=True,
        samesite="lax",
        secure=False,  # 仅监听 loopback 且无 TLS；对外暴露前必须改为 True
    )
    return response


@router.get("/csrf")
def csrf_token():
    """为无 Cookie 的客户端签发 CSRF 令牌；页面加载时也会自动下发。"""
    token = security.new_csrf_token()
    response = JSONResponse(success(csrf_token=token))
    dependencies.issue_csrf_cookie(response, token)
    return response


@router.post("/register")
def register(
    body: CredentialsRequest,
    request: Request,
    x_csrf_token: str = Header(default=""),
):
    dependencies.require_csrf(request, x_csrf_token)
    source = request.client.host if request.client else "unknown"
    try:
        user = accounts.register_user(body.email, body.password)
    except accounts.AuthError as exc:
        logger.info("Register rejected code=%s source=%s", exc.code, source)
        return auth_failed(exc)
    except IntegrityError:
        # Driver diagnostics may include email values; never log the exception,
        # SQL statement, parameters or traceback, including through Uvicorn.
        logger.error("Registration integrity constraint failure", extra={"event": "registration_integrity_failure"})
        raise HTTPException(status_code=500, detail="注册服务暂不可用") from None
    logger.info("Registered user id=%s", user.id)
    return JSONResponse(status_code=201, content=success(code="created", user=user.public))


@router.post("/login")
def login(
    body: CredentialsRequest,
    request: Request,
    x_csrf_token: str = Header(default=""),
):
    dependencies.require_csrf(request, x_csrf_token)
    source = request.client.host if request.client else "unknown"
    try:
        token = accounts.login(body.email, body.password, source)
    except accounts.AuthError as exc:
        logger.info("Login rejected code=%s source=%s", exc.code, source)
        return auth_failed(exc)
    user = accounts.current_user(token)
    if user is None:
        logger.error("Session unusable right after issuance")
        raise HTTPException(status_code=500, detail="会话创建异常")
    logger.info("Login succeeded user id=%s", user.id)
    return set_session_cookie(
        JSONResponse(success(user=user.public)), token
    )


@router.post("/logout")
def logout(request: Request, x_csrf_token: str = Header(default="")):
    dependencies.require_csrf(request, x_csrf_token)
    accounts.logout(dependencies.session_token(request))
    response = JSONResponse(success())
    response.delete_cookie(key=config.SESSION_COOKIE, path="/")
    return response


@router.get("/me")
def me(user: accounts.User = Depends(dependencies.require_user)):
    return success(user=user.public)

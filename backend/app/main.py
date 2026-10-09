"""FastAPI 组装与启动：注入数据库就绪状态与模型运行时。"""

from __future__ import annotations

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import dependencies
from app.api.v1 import api_keys as api_keys_routes
from app.api.v1 import auth as auth_routes
from app.api.v1 import admin as admin_routes
from app.api.v1 import inference as inference_routes
from app.api.v1 import statistics as statistics_routes
from app.api.v1 import gateway as gateway_routes
from app.api.v1 import admin_management as admin_management_routes
from app.core import config, security
from app.db import models
from app.services import model_runtime

logger = logging.getLogger("laya.api")

# 页面文件名与访问路径；管理页面需要登录会话，未登录跳转 /login。
PAGES = {
    "/keys": "api-keys.html",
    "/usage": "usage.html",
    "/billing": "billing.html",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    models.init_db()
    logger.info("MySQL schema ready for database %s", config.database_config().database)
    app.state.router = None
    app.state.device = 'external'
    if config.laya_runtime() == 'local':
        device = config.laya_device()
        app.state.router = model_runtime.build_router(device)
        app.state.device = device
        logger.info("Laya %s ready on %s", model_runtime.MODEL_NAME, device)
    yield


app = FastAPI(title="Laya 本地模型 API", version="1.0.0", lifespan=lifespan)
app.include_router(auth_routes.router)
app.include_router(admin_routes.router)
app.include_router(api_keys_routes.router)
app.include_router(statistics_routes.router)
app.include_router(inference_routes.router)
app.include_router(gateway_routes.router)
app.include_router(admin_management_routes.router)


@app.exception_handler(HTTPException)
async def flatten_auth_error(request: Request, exc: HTTPException):
    """鉴权与 Key 类错误返回平铺的 code/message；422 与 500 的既有 detail 结构不变。"""
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail, headers=exc.headers)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


class _NoCacheStaticFiles(StaticFiles):
    """构建产物随 npm run build 变化，禁用启发式缓存，只允许 304 复用。"""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


if config.FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        _NoCacheStaticFiles(directory=config.FRONTEND_DIST),
        name="assets",
    )


def _dist_page(name: str) -> FileResponse:
    page = config.FRONTEND_DIST / name
    if not page.exists():
        raise HTTPException(
            status_code=500, detail="页面未构建，请在 frontend 目录执行 npm run build"
        )
    return FileResponse(page, media_type="text/html; charset=utf-8")


def _with_csrf(request: Request, response: FileResponse) -> FileResponse:
    if not request.cookies.get(config.CSRF_COOKIE):
        dependencies.issue_csrf_cookie(response, security.new_csrf_token())
    return response


@app.get("/login", include_in_schema=False)
@app.get("/register", include_in_schema=False)
def login(request: Request):
    return _with_csrf(request, _dist_page("login.html"))


@app.get("/", include_in_schema=False)
def root(request: Request):
    user = dependencies.current_user(request)
    return RedirectResponse(("/admin" if user.is_admin else "/keys") if user else "/login")


@app.get("/keys", include_in_schema=False)
@app.get("/usage", include_in_schema=False)
@app.get("/billing", include_in_schema=False)
def managed_page(request: Request):
    name = PAGES[request.url.path]
    if dependencies.current_user(request) is None:
        return RedirectResponse("/login", status_code=302)
    # 会话校验必须在每次导航时执行，不能命中浏览器缓存的页面壳。
    response = _with_csrf(request, _dist_page(name))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health(request: Request):
    return {
        "status": "ok",
        "model": model_runtime.MODEL_NAME if request.app.state.router is not None else None,
        "runtime": config.laya_runtime(),
        "device": request.app.state.device,
    }


@app.get("/admin", include_in_schema=False)
@app.get("/admin/settings", include_in_schema=False)
@app.get("/admin/users", include_in_schema=False)
def admin_page(request: Request):
    user = dependencies.current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=302)
    dependencies.require_admin(user)
    name = {
        "/admin": "admin.html",
        "/admin/settings": "admin-settings.html",
        "/admin/users": "admin-users.html",
    }[request.url.path]
    response = _with_csrf(request, _dist_page(name))
    response.headers["Cache-Control"] = "no-store"
    return response

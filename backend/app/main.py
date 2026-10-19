"""FastAPI 组装与启动：注入数据库就绪状态与模型运行时。"""

from __future__ import annotations

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.v1 import api_keys as api_keys_routes
from app.api.v1 import auth as auth_routes
from app.api.v1 import platform as platform_routes
from app.api.v1 import admin as admin_routes
from app.api.v1 import inference as inference_routes
from app.api.v1 import statistics as statistics_routes
from app.api.v1 import gateway as gateway_routes
from app.api.v1 import admin_management as admin_management_routes
from app.core import config
from app.db import migrations
from app.services.inference import model_runtime

logger = logging.getLogger("laya.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.request_limits_config()
    migrations.init_db()
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
app.include_router(platform_routes.router)
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


@app.get("/health")
def health(request: Request):
    return {
        "status": "ok",
        "model": model_runtime.MODEL_NAME if request.app.state.router is not None else None,
        "runtime": config.laya_runtime(),
        "device": request.app.state.device,
    }

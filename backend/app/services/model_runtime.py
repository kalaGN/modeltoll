"""Laya 模型运行时：单实例构建与串行推理锁，保护 MPS 内存。"""

from __future__ import annotations

import threading

from app.core import config

config.configure_model_cache()

from laya import Router  # noqa: E402  (HF_HOME 必须先设置)

MODEL_NAME = "multilingual"
inference_lock = threading.Lock()


def build_router(device: str) -> Router:
    router = Router(device=device, default=MODEL_NAME, max_loaded=1)
    router.load(MODEL_NAME)
    return router

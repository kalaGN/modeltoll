"""本地 Laya 模型服务，使用单实例和串行推理保护 MPS 内存。"""

import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Any, Literal

from customer_service_test import Router, analyse
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger("laya.api")
inference_lock = threading.Lock()


class CustomerServiceRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.message.strip():
            raise ValueError("message 不能为空白")
        return self


class Question(BaseModel):
    type: Literal["choice", "score", "noul"]
    instructions: str = Field(min_length=1, max_length=2000)
    criteria: dict[str, str] | list[str] | None = None

    @model_validator(mode="after")
    def validate_criteria(self):
        if not self.instructions.strip():
            raise ValueError("instructions 不能为空白")
        if self.type == "choice":
            if not isinstance(self.criteria, dict) or not 2 <= len(self.criteria) <= 20:
                raise ValueError("choice.criteria 必须是包含 2 到 20 项的对象")
        elif self.type == "score":
            if not isinstance(self.criteria, list) or not 2 <= len(self.criteria) <= 20:
                raise ValueError("score.criteria 必须是包含 2 到 20 项的列表")
        elif self.criteria is not None:
            if not isinstance(self.criteria, dict) or not set(self.criteria) <= {"true", "false"}:
                raise ValueError("noul.criteria 只支持 true/false 描述")
        if self.criteria is not None:
            values = self.criteria.values() if isinstance(self.criteria, dict) else self.criteria
            if any(not v.strip() or len(v) > 1000 for v in values):
                raise ValueError("criteria 描述必须非空，且不超过 1000 字符")
        return self


class PredictRequest(BaseModel):
    state: str | dict[str, Any] | list[Any]
    questions: dict[str, Question] = Field(min_length=1, max_length=20)
    lang: str = Field(default="zh", min_length=2, max_length=20)

    @model_validator(mode="after")
    def limit_state(self):
        import json

        if len(json.dumps(self.state, ensure_ascii=False)) > 16000:
            raise ValueError("state 不能超过 16000 字符")
        return self


@asynccontextmanager
async def lifespan(app: FastAPI):
    device = os.environ.get("LAYA_DEVICE", "mps")
    if device not in {"mps", "cpu"}:
        raise ValueError("LAYA_DEVICE 只支持 mps 或 cpu")
    router = Router(device=device, default="multilingual", max_loaded=1)
    router.load("multilingual")
    app.state.router = router
    app.state.device = device
    logger.info("Laya multilingual ready on %s", device)
    yield


app = FastAPI(title="Laya 本地模型 API", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health(request: Request):
    return {"status": "ok", "model": "multilingual", "device": request.app.state.device}


@app.post("/v1/customer-service/analyze")
def customer_service(body: CustomerServiceRequest, request: Request):
    try:
        with inference_lock:
            return analyse(body.message, router=request.app.state.router)
    except Exception:
        logger.exception("Customer service inference failed")
        raise HTTPException(status_code=500, detail="模型推理失败，请查看服务日志")


@app.post("/v1/predict")
def predict(body: PredictRequest, request: Request):
    questions = {
        key: value.model_dump(exclude_none=True)
        for key, value in body.questions.items()
    }
    try:
        with inference_lock:
            return request.app.state.router.predict(
                body.state, questions, model="multilingual", lang=body.lang
            )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        logger.exception("Structured prediction failed")
        raise HTTPException(status_code=500, detail="模型推理失败，请查看服务日志")

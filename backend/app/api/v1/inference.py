"""两个推理接口：新增 API Key 鉴权与调用记账。

响应字段、模型语义与 200/422/500 状态码保持迁移前一致（验收 A11）；
归属与计量写入调用记录，并用 X-Request-Id 响应头回传同一请求标识。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api import dependencies
from app.api.dependencies import require_api_key
from app.schemas.inference import CustomerServiceRequest, PredictRequest
from app.services import api_keys, customer_service, idempotency, inference, model_runtime

logger = logging.getLogger("laya.api.inference")
router = APIRouter(tags=["inference"])

ANALYZE_ENDPOINT = "/v1/customer-service/analyze"
PREDICT_ENDPOINT = "/v1/predict"


def _prepare_idempotency(key: str | None, endpoint: str, model: str, body: Any):
    try:
        return idempotency.prepare(key, endpoint, model, body.model_dump(mode="json"))
    except ValueError:
        raise HTTPException(422, detail={"code": "invalid_idempotency_key", "message": "Idempotency-Key需为1–128个可见ASCII字符（不含空格）"}) from None


def _begin_call(endpoint: str, principal: api_keys.Principal, model: str, token):
    try:
        if token is None:
            return inference.begin(endpoint, principal, model)
        return inference.begin(endpoint, principal, model, idempotency=token)
    except inference.IdempotencyConflict as exc:
        raise HTTPException(
            409, detail={"code": exc.code, "message": "该Idempotency-Key已使用，请核查原调用", "call_id": exc.call_id},
            headers={"X-Request-Id": exc.call_id},
        ) from None


def _key_revoked(call: inference.Call, principal: api_keys.Principal) -> None:
    """排队期间 Key 被撤销或账号被停用时停止推理（设计 §15）。"""
    if api_keys.still_valid(principal.api_key_id):
        return
    inference.interrupted(call, "key_revoked", 401)
    raise HTTPException(
        status_code=401,
        detail={"code": "invalid_api_key", "message": "API Key 缺失、无效或已撤销"},
        headers={"X-Request-Id": call.id},
    )


def _fail(call: inference.Call, error_code: str, status: int, detail: Any) -> None:
    try:
        inference.failed(call, error_code, status)
    except Exception:
        logger.exception("Failure accounting write failed id=%s", call.id)
        raise HTTPException(
            status_code=500,
            detail={"code": "billing_unavailable", "message": "用量记账失败，请查看服务日志"},
            headers={"X-Request-Id": call.id},
        ) from None
    if status == 500:
        logger.exception("Inference failed code=%s id=%s", error_code, call.id)
    raise HTTPException(status_code=status, detail=detail, headers={"X-Request-Id": call.id})


def _settle(call: inference.Call, usage: dict[str, Any]) -> None:
    """终态与费用在同一事务提交后才允许返回成功（设计 §15）。"""
    try:
        inference.capture_success(call, usage)
        inference.succeeded(call, usage)
    except inference.UsageUnavailable:
        # 库内已是 failed/usage_unavailable/pending，对外同样不能声称成功。
        logger.error("Model returned no token usage id=%s", call.id)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "usage_unavailable",
                "message": "模型未返回 Token 用量，本次调用未计费，请稍后重试",
            },
            headers={"X-Request-Id": call.id},
        ) from None
    except Exception:
        # 保留 running 遗留记录供恢复巡检，不对外声称已计费。
        logger.exception("Terminal accounting write failed id=%s", call.id)
        raise HTTPException(
            status_code=500,
            detail={"code": "billing_unavailable", "message": "用量记账失败，请查看服务日志"},
            headers={"X-Request-Id": call.id},
        ) from None


def _postprocessing_failed(call: inference.Call, usage: dict[str, Any]) -> None:
    try:
        inference.keep_usage(call, usage)
    except (ValueError, TypeError):
        logger.error("Invalid postprocessing usage id=%s", call.id)
    except Exception:
        logger.exception("Postprocessing usage write failed id=%s", call.id)
        raise HTTPException(
            500, detail={"code": "billing_unavailable", "message": "用量记账失败，请查看服务日志"},
            headers={"X-Request-Id": call.id},
        ) from None
    _fail(call, "inference_error", 500, "模型推理失败，请查看服务日志")


def _response(call: inference.Call, payload: Any, usage: dict[str, Any]) -> JSONResponse:
    # JSON编码必须先成功，才可拥有用于补账的成功回执。
    try:
        return JSONResponse(payload, headers={"X-Request-Id": call.id})
    except (ValueError, TypeError):
        _postprocessing_failed(call, usage)


@router.post(ANALYZE_ENDPOINT)
def analyze(
    body: CustomerServiceRequest,
    request: Request,
    principal: api_keys.Principal = Depends(require_api_key),
    idempotency_key: str | None = Header(default=None),
):
    _require_local_router(request)
    token = _prepare_idempotency(idempotency_key, ANALYZE_ENDPOINT, model_runtime.MODEL_NAME, body)
    with dependencies.admit_inference(principal):
        call = _begin_call(ANALYZE_ENDPOINT, principal, model_runtime.MODEL_NAME, token)
        with model_runtime.inference_lock:
            _key_revoked(call, principal)
            inference.mark_running(call)
            try:
                payload, usage = customer_service.analyse_with_usage(
                    body.message, router=request.app.state.router
                )
            except customer_service.AnalysisPostprocessingError as exc:
                _postprocessing_failed(call, exc.usage)
            except Exception:
                _fail(call, "inference_error", 500, "模型推理失败，请查看服务日志")
        response = _response(call, payload, usage)
        _settle(call, usage)
        return response


@router.post(PREDICT_ENDPOINT)
def predict(
    body: PredictRequest,
    request: Request,
    principal: api_keys.Principal = Depends(require_api_key),
    idempotency_key: str | None = Header(default=None),
):
    _require_local_router(request)
    questions = {key: value.model_dump(exclude_none=True) for key, value in body.questions.items()}
    token = _prepare_idempotency(idempotency_key, PREDICT_ENDPOINT, model_runtime.MODEL_NAME, body)
    with dependencies.admit_inference(principal):
        call = _begin_call(PREDICT_ENDPOINT, principal, model_runtime.MODEL_NAME, token)
        with model_runtime.inference_lock:
            _key_revoked(call, principal)
            inference.mark_running(call)
            try:
                result = request.app.state.router.predict(
                    body.state, questions, model=model_runtime.MODEL_NAME, lang=body.lang
                )
            except (ValueError, TypeError) as exc:
                _fail(call, "invalid_request", 422, str(exc))
            except Exception:
                _fail(call, "inference_error", 500, "模型推理失败，请查看服务日志")
        response = _response(call, result, result.get("usage", {}))
        _settle(call, result.get("usage", {}))
        return response


def _require_local_router(request: Request) -> None:
    if getattr(request.app.state, 'router', None) is None:
        raise HTTPException(503, detail={'code': 'local_model_disabled', 'message': '当前模式未加载本地 Laya 模型'})

"""两个推理接口：新增 API Key 鉴权与调用记账。

响应字段、模型语义与 200/422/500 状态码保持迁移前一致（验收 A11）；
归属与计量写入调用记录，并用 X-Request-Id 响应头回传同一请求标识。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api import dependencies, inference_support
from app.api.dependencies import require_api_key
from app.schemas.inference import CustomerServiceRequest, PredictRequest
from app.services import api_keys, customer_service, inference, model_runtime

router = APIRouter(tags=["inference"])

ANALYZE_ENDPOINT = "/v1/customer-service/analyze"
PREDICT_ENDPOINT = "/v1/predict"


@router.post(ANALYZE_ENDPOINT)
def analyze(
    body: CustomerServiceRequest,
    request: Request,
    principal: api_keys.Principal = Depends(require_api_key),
    idempotency_key: str | None = Header(default=None),
):
    _require_local_router(request)
    token = inference_support.prepare_idempotency(idempotency_key, ANALYZE_ENDPOINT, model_runtime.MODEL_NAME, body)
    with dependencies.admit_inference(principal):
        call = inference_support.begin_call(ANALYZE_ENDPOINT, principal, model_runtime.MODEL_NAME, token)
        with model_runtime.inference_lock:
            inference_support.key_revoked(call, principal)
            inference.mark_running(call)
            try:
                payload, usage = customer_service.analyse_with_usage(
                    body.message, router=request.app.state.router
                )
            except customer_service.AnalysisPostprocessingError as exc:
                inference_support.postprocessing_failed(call, exc.usage)
            except Exception:
                inference_support.fail(call, "inference_error", 500, "模型推理失败，请查看服务日志")
        response = inference_support.response(call, payload, usage)
        inference_support.settle(call, usage)
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
    token = inference_support.prepare_idempotency(idempotency_key, PREDICT_ENDPOINT, model_runtime.MODEL_NAME, body)
    with dependencies.admit_inference(principal):
        call = inference_support.begin_call(PREDICT_ENDPOINT, principal, model_runtime.MODEL_NAME, token)
        with model_runtime.inference_lock:
            inference_support.key_revoked(call, principal)
            inference.mark_running(call)
            try:
                result = request.app.state.router.predict(
                    body.state, questions, model=model_runtime.MODEL_NAME, lang=body.lang
                )
            except (ValueError, TypeError) as exc:
                inference_support.fail(call, "invalid_request", 422, str(exc))
            except Exception:
                inference_support.fail(call, "inference_error", 500, "模型推理失败，请查看服务日志")
        response = inference_support.response(call, result, result.get("usage", {}))
        inference_support.settle(call, result.get("usage", {}))
        return response


def _require_local_router(request: Request) -> None:
    if getattr(request.app.state, 'router', None) is None:
        raise HTTPException(503, detail={'code': 'local_model_disabled', 'message': '当前模式未加载本地 Laya 模型'})

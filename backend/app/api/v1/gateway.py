"""平台 Key 保护的文字网关和管理员连接配置。"""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.routing import APIRoute
from app.api import dependencies, inference_support
from app.schemas.gateway import ChatRequest, ConnectionRequest
from app.services import accounts, api_keys, billing, gateway, inference, model_runtime

class BoundedJsonRoute(APIRoute):
    """JSON 解析前限制字节数，包括不带 Content-Length 的分块请求。"""
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request: Request):
            if request.method in {'POST', 'PUT'}:
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 256 * 1024:
                        raise HTTPException(413, detail={'code': 'body_too_large', 'message': '网关请求不能超过 256 KB'})
                    body.extend(chunk)
                request._body = bytes(body)
            return await handler(request)
        return bounded


router = APIRouter(tags=['model gateway'], route_class=BoundedJsonRoute)


def error(exc: gateway.GatewayError):
    return HTTPException(status_code=exc.status, detail={'code': exc.code, 'message': exc.message})


def enabled_connection() -> ConnectionRequest:
    value = gateway.connection()
    if value is None or not value.enabled:
        raise HTTPException(503, detail={'code': 'model_not_configured', 'message': '管理员尚未启用模型连接'})
    return value


@router.get('/v1/admin/model-connection')
def get_connection(user: accounts.User = Depends(dependencies.require_admin)):
    return {'code': 'ok', **gateway.public_connection(gateway.connection())}


@router.put('/v1/admin/model-connection')
def save_connection(body: ConnectionRequest, request: Request,
                    user: accounts.User = Depends(dependencies.require_admin), x_csrf_token: str = Header(default='')):
    dependencies.require_csrf(request, x_csrf_token)
    try:
        return {'code': 'ok', **gateway.save_connection(body)}
    except gateway.GatewayError as exc:
        raise error(exc) from None


@router.post('/v1/admin/model-connection/test')
def test_connection(body: ConnectionRequest, request: Request,
                    user: accounts.User = Depends(dependencies.require_admin), x_csrf_token: str = Header(default='')):
    dependencies.require_csrf(request, x_csrf_token)
    try:
        return {'code': 'ok', **gateway.test_connection(body)}
    except gateway.GatewayError as exc:
        raise error(exc) from None


@router.get('/v1/models')
def models(principal: api_keys.Principal = Depends(dependencies.require_api_key)):
    value = enabled_connection()
    return {'object': 'list', 'data': [{'id': value.model, 'object': 'model', 'created': 0, 'owned_by': 'self-hosted'}]}


@router.post('/v1/chat/completions')
def chat(body: ChatRequest, request: Request, principal: api_keys.Principal = Depends(dependencies.require_api_key),
         idempotency_key: str | None = Header(default=None)):
    value = enabled_connection()
    if body.model != value.model:
        raise HTTPException(404, detail={'code': 'model_not_found', 'message': '只能调用管理员配置的模型'})
    token = inference_support.prepare_idempotency(idempotency_key, '/v1/chat/completions', value.model, body)
    with dependencies.admit_inference(principal):
        try:
            call = inference_support.begin_call('/v1/chat/completions', principal, value.model, token)
        except billing.NoPricingRule:
            raise HTTPException(503, detail={'code': 'pricing_unavailable', 'message': '模型尚无生效价格，请联系管理员'}) from None
        if not model_runtime.inference_lock.acquire(timeout=30):
            inference.interrupted(call, 'queue_timeout', 503)
            raise HTTPException(503, detail={'code': 'queue_timeout', 'message': '推理排队超时，请稍后重试'})
        try:
            inference_support.key_revoked(call, principal)
            inference.mark_running(call)
            try:
                payload, usage = gateway.chat(value, body)
            except gateway.GatewayError as exc:
                inference.failed(call, exc.code, exc.status)
                failure = error(exc)
                failure.headers = {'X-Request-Id': call.id}
                raise failure from None
            try:
                response = inference_support.response(call, payload, usage)
                inference_support.settle(call, usage)
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), 'X-Request-Id': call.id}
                raise
            return response
        finally:
            model_runtime.inference_lock.release()

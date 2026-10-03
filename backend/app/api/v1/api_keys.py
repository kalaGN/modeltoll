"""Key 申请、列表与撤销。全部走登录会话，归属只取会话里的 user_id。"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api import dependencies
from app.schemas.api_keys import RevokeRequest
from app.services import accounts, api_keys

logger = logging.getLogger("laya.api.keys")
router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])


def _as_http(exc: api_keys.ApiKeyError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})


@router.post("")
def create_key(
    request: Request,
    user: accounts.User = Depends(dependencies.require_user),
    x_csrf_token: str = Header(default=""),
):
    dependencies.require_csrf(request, x_csrf_token)
    record, secret = api_keys.create(user.id)
    logger.info("API key created id=%s user_id=%s", record.id, user.id)
    return JSONResponse(
        status_code=201,
        content={
            "code": "created",
            "api_key": record.public,
            "secret": secret,
            "call_example": _example(secret),
        },
    )


@router.get("")
def list_keys(user: accounts.User = Depends(dependencies.require_user)):
    records = api_keys.list_for_user(user.id)
    active = [row.public for row in records if row.status == "active"]
    return {
        "code": "ok",
        "items": [row.public for row in records],
        "summary": {
            "total": len(records),
            "active": len(active),
            "revoked": len(records) - len(active),
        },
    }


@router.post("/{key_id}/revoke")
def revoke_key(
    key_id: str,
    request: Request,
    body: RevokeRequest | None = None,
    user: accounts.User = Depends(dependencies.require_user),
    x_csrf_token: str = Header(default=""),
):
    dependencies.require_csrf(request, x_csrf_token)
    if not _is_uuid(key_id):
        raise _as_http(api_keys.ApiKeyNotFound())
    try:
        record = api_keys.revoke(user.id, key_id)
    except api_keys.ApiKeyError as exc:
        raise _as_http(exc) from None
    logger.info("API key revoked id=%s user_id=%s", key_id, user.id)
    return {"code": "ok", "api_key": record.public}


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def _example(secret: str) -> str:
    """创建响应里给出的调用示例，与实际契约一致（验收 A12）。"""
    payload = json.dumps(
        {
            "state": {"message": "请帮我退款"},
            "lang": "zh",
            "questions": {
                "refund_requested": {"type": "noul", "instructions": "客户是否要求退款？"}
            },
        },
        ensure_ascii=False,
    )
    return (
        "curl -X POST http://127.0.0.1:8000/v1/predict \\\n"
        f'  -H "Authorization: Bearer {secret}" \\\n'
        '  -H "Content-Type: application/json" \\\n'
        f"  -d '{payload}'"
    )

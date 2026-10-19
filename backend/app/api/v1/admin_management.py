"""Administrator-only account/key actions; all writes require CSRF."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from app.api import dependencies
from app.api.errors import http_error
from app.api.responses import success
from app.schemas.admin_management import ReasonRequest, UserStatusRequest
from app.services import accounts, admin_management as management

router = APIRouter(prefix='/v1/admin', tags=['admin-management'])


def _call(function, *args):
    try:
        return success(**function(*args))
    except management.ManagementError as exc:
        raise http_error(exc.status_code, exc.code, exc.message) from None


@router.get('/users')
def list_users(q: str = Query('', max_length=254), status: Literal['active', 'disabled'] | None = None,
               page: int = Query(1, ge=1, le=10000), limit: int = Query(20, ge=1, le=100),
               actor: accounts.User = Depends(dependencies.require_admin)):
    return _call(management.list_users, q, status or '', page, limit)


@router.patch('/users/{user_id}/status')
def set_status(user_id: UUID, body: UserStatusRequest, request: Request,
               actor: accounts.User = Depends(dependencies.require_admin),
               x_csrf_token: str = Header('')):
    dependencies.require_csrf(request, x_csrf_token)
    return _call(management.set_user_status, actor.id, str(user_id), body.status, body.reason)


@router.get('/users/{user_id}/api-keys')
def list_keys(user_id: UUID, page: int = Query(1, ge=1, le=10000),
              limit: int = Query(20, ge=1, le=100),
              actor: accounts.User = Depends(dependencies.require_admin)):
    return _call(management.list_keys, str(user_id), page, limit)


@router.post('/api-keys/{key_id}/revoke')
def revoke_key(key_id: UUID, body: ReasonRequest, request: Request,
               actor: accounts.User = Depends(dependencies.require_admin),
               x_csrf_token: str = Header('')):
    dependencies.require_csrf(request, x_csrf_token)
    return _call(management.revoke_key, actor.id, str(key_id), body.reason)


@router.get('/audit-events')
def list_audit(page: int = Query(1, ge=1, le=10000), limit: int = Query(20, ge=1, le=100),
               actor: accounts.User = Depends(dependencies.require_admin)):
    return _call(management.list_audit_events, page, limit)

"""Administrator account/key management with atomic, non-secret audit records."""

from __future__ import annotations

import uuid
from typing import Any

from app.core import security
from app.db import session
from app.repositories import administration as repository
from app.core.time import utc_now
from app.core.time import iso_utc


class ManagementError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def _user(row: dict[str, Any]) -> dict[str, Any]:
    return {'id': row['id'], 'email': row['email'], 'status': row['status'],
            'is_admin': bool(row['is_admin']), 'created_at': iso_utc(row['created_at']),
            'last_login_at': iso_utc(row['last_login_at'])}


def _key(row: dict[str, Any]) -> dict[str, Any]:
    return {'id': row['id'], 'name': row['name'],
            'display': security.masked_key(row['display_prefix'], row['last_four']),
            'status': ('deleted' if row['deleted_at'] else 'revoked' if row['revoked_at'] else 'active'),
            **{name: iso_utc(row[name]) for name in
               ('created_at', 'last_used_at', 'revoked_at', 'deleted_at')}}


def _page(items: list, page: int, limit: int, total: int) -> dict[str, Any]:
    return {'items': items, 'page': page, 'limit': limit,
            'total': total, 'has_more': page * limit < total}


def list_users(q: str = '', status: str = '', page: int = 1, limit: int = 20) -> dict:
    with session.read_session() as db:
        total, rows = repository.list_users(db, q, status, page, limit)
        items = [_user(row) for row in rows]
    return _page(items, page, limit, total)


def list_keys(user_id: str, page: int = 1, limit: int = 20) -> dict:
    with session.read_session() as db:
        if not repository.user_exists(db, user_id):
            raise ManagementError(404, 'user_not_found', '用户不存在')
        total, rows = repository.list_keys(db, user_id, page, limit)
        items = [_key(row) for row in rows]
    return _page(items, page, limit, total)


def list_audit_events(page: int = 1, limit: int = 20) -> dict:
    with session.read_session() as db:
        total, rows = repository.list_audit_events(db, page, limit)
        items = [{**row, 'created_at': iso_utc(row['created_at'])} for row in rows]
    return _page(items, page, limit, total)


def _locked_user(cur: Any, user_id: str) -> dict | None:
    return repository.lock_user(cur, user_id)


def _locked_users(cur: Any, actor_id: str, target_id: str) -> dict[str, dict | None]:
    # Consistent order also handles two admins revoking each other's keys.
    return {user_id: _locked_user(cur, user_id) for user_id in sorted({actor_id, target_id})}


def _actor(actor: dict | None) -> None:
    if actor is None or not actor['is_admin'] or actor['status'] != 'active':
        raise ManagementError(403, 'admin_required', '需要启用的管理员权限')


def _audit(cur: Any, actor_id: str, target_user_id: str, target_key_id: str | None,
           action: str, previous: str, new: str, reason: str) -> None:
    repository.audit(cur, str(uuid.uuid4()), actor_id, target_user_id, target_key_id,
                     action, previous, new, reason)


def set_user_status(actor_id: str, user_id: str, status: str, reason: str) -> dict:
    with session.unit_of_work() as cur:
        users = _locked_users(cur, actor_id, user_id)
        _actor(users[actor_id])
        target = users[user_id]
        if target is None:
            raise ManagementError(404, 'user_not_found', '用户不存在')
        if target['is_admin']:
            raise ManagementError(409, 'protected_admin', '不能通过此功能更改管理员账号状态')
        changed = target['status'] != status
        if changed:
            repository.set_user_status(cur, user_id, status)
            if status == 'disabled':
                repository.revoke_sessions(cur, user_id)
            _audit(cur, actor_id, user_id, None, 'user.status_changed', target['status'], status, reason)
        result = _user({**target, 'status': status})
    return {'user': result, 'changed': changed}


def revoke_key(actor_id: str, key_id: str, reason: str) -> dict:
    with session.unit_of_work() as cur:
        # Discover the immutable owner, then lock all users in UUID order, and
        # only then the key. User status changes use the same user lock order.
        owner = repository.key_owner(cur, key_id)
        if owner is None:
            raise ManagementError(404, 'api_key_not_found', 'API Key 不存在')
        users = _locked_users(cur, actor_id, owner['user_id'])
        _actor(users[actor_id])
        key = repository.lock_key(cur, key_id, owner['user_id'])
        if key is None:
            raise ManagementError(404, 'api_key_not_found', 'API Key 不存在')
        changed = key['revoked_at'] is None and key['deleted_at'] is None
        if changed:
            now = utc_now()
            repository.revoke_key(cur, key_id, now)
            _audit(cur, actor_id, key['user_id'], key_id, 'api_key.revoked', 'active', 'revoked', reason)
            key = {**key, 'revoked_at': now}
        result = _key(key)
    return {'api_key': result, 'changed': changed}

"""Administrator account/key management with atomic, non-secret audit records."""

from __future__ import annotations

import uuid
from typing import Any

from app.core import security
from app.db import session
from app.services.accounts import utc_now
from app.core.time import iso_utc


class ManagementError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


USER_COLUMNS = 'id, email, status, is_admin, created_at, last_login_at'
KEY_COLUMNS = ('id, user_id, name, display_prefix, last_four, created_at,'
               ' last_used_at, revoked_at, deleted_at')


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
    clauses, args = [], []
    if q:
        # Explicit escape character treats %, _ and the escape itself literally.
        escaped = q.replace('!', '!!').replace('%', '!%').replace('_', '!_')
        clauses.append("email LIKE %s ESCAPE '!'")
        args.append(f'%{escaped}%')
    if status:
        clauses.append('status = %s')
        args.append(status)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    with session.cursor() as cur:
        cur.execute('SELECT COUNT(*) AS total FROM users' + where, tuple(args))
        total = cur.fetchone()['total']
        cur.execute(f'SELECT {USER_COLUMNS} FROM users' + where +
                    ' ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s',
                    (*args, limit, (page - 1) * limit))
        items = [_user(row) for row in cur.fetchall()]
    return _page(items, page, limit, total)


def list_keys(user_id: str, page: int = 1, limit: int = 20) -> dict:
    with session.cursor() as cur:
        cur.execute('SELECT id FROM users WHERE id = %s', (user_id,))
        if cur.fetchone() is None:
            raise ManagementError(404, 'user_not_found', '用户不存在')
        cur.execute('SELECT COUNT(*) AS total FROM api_keys WHERE user_id = %s', (user_id,))
        total = cur.fetchone()['total']
        cur.execute(f'SELECT {KEY_COLUMNS} FROM api_keys WHERE user_id = %s'
                    ' ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s',
                    (user_id, limit, (page - 1) * limit))
        items = [_key(row) for row in cur.fetchall()]
    return _page(items, page, limit, total)


def list_audit_events(page: int = 1, limit: int = 20) -> dict:
    with session.cursor() as cur:
        cur.execute('SELECT COUNT(*) AS total FROM admin_audit_events')
        total = cur.fetchone()['total']
        cur.execute('SELECT a.id, a.actor_id, actor.email AS actor_email,'
                    ' a.target_user_id, target.email AS target_email, a.target_key_id,'
                    ' a.action, a.previous_status, a.new_status, a.reason, a.created_at'
                    ' FROM admin_audit_events a JOIN users actor ON actor.id = a.actor_id'
                    ' JOIN users target ON target.id = a.target_user_id'
                    ' ORDER BY a.created_at DESC, a.id DESC LIMIT %s OFFSET %s',
                    (limit, (page - 1) * limit))
        items = [{**row, 'created_at': iso_utc(row['created_at'])} for row in cur.fetchall()]
    return _page(items, page, limit, total)


def _locked_user(cur: Any, user_id: str) -> dict | None:
    cur.execute(f'SELECT {USER_COLUMNS} FROM users WHERE id = %s FOR UPDATE', (user_id,))
    return cur.fetchone()


def _locked_users(cur: Any, actor_id: str, target_id: str) -> dict[str, dict | None]:
    # Consistent order also handles two admins revoking each other's keys.
    return {user_id: _locked_user(cur, user_id) for user_id in sorted({actor_id, target_id})}


def _actor(actor: dict | None) -> None:
    if actor is None or not actor['is_admin'] or actor['status'] != 'active':
        raise ManagementError(403, 'admin_required', '需要启用的管理员权限')


def _audit(cur: Any, actor_id: str, target_user_id: str, target_key_id: str | None,
           action: str, previous: str, new: str, reason: str) -> None:
    cur.execute('INSERT INTO admin_audit_events'
                ' (id, actor_id, target_user_id, target_key_id, action,'
                ' previous_status, new_status, reason, created_at)'
                ' VALUES (%s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(3))',
                (str(uuid.uuid4()), actor_id, target_user_id, target_key_id,
                 action, previous, new, reason))


def set_user_status(actor_id: str, user_id: str, status: str, reason: str) -> dict:
    with session.transaction() as cur:
        users = _locked_users(cur, actor_id, user_id)
        _actor(users[actor_id])
        target = users[user_id]
        if target is None:
            raise ManagementError(404, 'user_not_found', '用户不存在')
        if target['is_admin']:
            raise ManagementError(409, 'protected_admin', '不能通过此功能更改管理员账号状态')
        changed = target['status'] != status
        if changed:
            cur.execute('UPDATE users SET status = %s, updated_at = UTC_TIMESTAMP(3) WHERE id = %s',
                        (status, user_id))
            if status == 'disabled':
                cur.execute('UPDATE user_sessions SET revoked_at = UTC_TIMESTAMP(3)'
                            ' WHERE user_id = %s AND revoked_at IS NULL', (user_id,))
            _audit(cur, actor_id, user_id, None, 'user.status_changed', target['status'], status, reason)
        result = _user({**target, 'status': status})
    return {'user': result, 'changed': changed}


def revoke_key(actor_id: str, key_id: str, reason: str) -> dict:
    with session.transaction() as cur:
        # Discover the immutable owner, then lock all users in UUID order, and
        # only then the key. User status changes use the same user lock order.
        cur.execute('SELECT user_id FROM api_keys WHERE id = %s', (key_id,))
        owner = cur.fetchone()
        if owner is None:
            raise ManagementError(404, 'api_key_not_found', 'API Key 不存在')
        users = _locked_users(cur, actor_id, owner['user_id'])
        _actor(users[actor_id])
        cur.execute(f'SELECT {KEY_COLUMNS} FROM api_keys WHERE id = %s AND user_id = %s FOR UPDATE',
                    (key_id, owner['user_id']))
        key = cur.fetchone()
        if key is None:
            raise ManagementError(404, 'api_key_not_found', 'API Key 不存在')
        changed = key['revoked_at'] is None and key['deleted_at'] is None
        if changed:
            now = utc_now()
            cur.execute('UPDATE api_keys SET revoked_at = %s WHERE id = %s', (now, key_id))
            _audit(cur, actor_id, key['user_id'], key_id, 'api_key.revoked', 'active', 'revoked', reason)
            key = {**key, 'revoked_at': now}
        result = _key(key)
    return {'api_key': result, 'changed': changed}

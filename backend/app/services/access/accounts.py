"""账号注册、登录、会话与登录限速。归属认定只来自服务端会话，不信任客户端提交。"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.core import config, security
from app.core.time import utc_now
from app.core.validation import normalize_email, valid_email_shape
from app.db import session
from app.repositories import accounts as repository


class AuthError(Exception):
    status_code = 400
    code = "auth_error"
    message = "认证失败"


class InvalidCredentials(AuthError):
    status_code = 401
    code = "invalid_credentials"
    message = "邮箱或密码不正确"


class AccountLocked(AuthError):
    status_code = 429
    code = "account_locked"
    message = "失败次数过多，账号暂时锁定，请稍后再试"


class EmailAlreadyRegistered(AuthError):
    status_code = 409
    code = "email_already_registered"
    message = "该邮箱无法注册"


class DisabledAccount(AuthError):
    status_code = 403
    code = "account_disabled"
    message = "账号已停用"


@dataclass(frozen=True)
class User:
    id: str
    email: str
    is_admin: bool = False

    @property
    def public(self) -> dict[str, Any]:
        return {"id": self.id, "email": self.email, "is_admin": self.is_admin}


def _throttle_key(normalized_email: str, source: str) -> str:
    return f"{normalized_email}|{source}"


def _select_user(cur: Any, normalized_email: str) -> dict[str, Any] | None:
    return repository.login_user(cur, normalized_email)


def _locked(cur: Any, key: str) -> bool:
    row = repository.throttle(cur, key)
    return bool(row and row["locked_until"] and row["locked_until"] > utc_now())


def _record_failure(cur: Any, key: str) -> None:
    now = utc_now()
    repository.record_failure(
        cur, key, now, config.FAILED_WINDOW_MINUTES * 60, config.MAX_FAILED_ATTEMPTS,
        now + datetime.timedelta(minutes=config.LOCK_MINUTES),
    )


def register_user(email: str, password: str) -> User:
    normalized = normalize_email(email)
    password_hash = security.hash_password(password)
    try:
        with session.unit_of_work() as cur:
            repository.create_user(cur, str(uuid.uuid4()), email.strip(), normalized, password_hash)
    except IntegrityError:
        raise EmailAlreadyRegistered() from None
    return _fetch_user(normalized)


def _fetch_user(normalized: str) -> User:
    with session.read_session() as cur:
        row = _select_user_by_normalized(cur, normalized)
    return User(id=row["id"], email=row["email"], is_admin=bool(row["is_admin"]))


def _select_user_by_normalized(cur: Any, normalized: str) -> dict[str, Any] | None:
    return repository.public_user(cur, normalized)


def login(email: str, password: str, source: str) -> str:
    """校验凭据并签发会话，返回明文会话 Token；失败抛出 AuthError。"""
    normalized = normalize_email(email)
    key = _throttle_key(normalized, source)

    # 口令验证开销较大，先在不持有写事务的读取中完成，再用短事务落终态。
    with session.read_session() as cur:
        locked = _locked(cur, key)
        row = _select_user(cur, normalized)
    if locked:
        raise AccountLocked()

    if row is None:
        security.verify_password(security.dummy_hash(), password)
        authenticated = False
    else:
        authenticated = security.verify_password(row["password_hash"], password)

    outcome: AuthError | None
    token = ""
    with session.unit_of_work() as cur:
        if not authenticated:
            _record_failure(cur, key)
            outcome = InvalidCredentials()
        elif _locked(cur, key):
            outcome = AccountLocked()
        else:
            # Serialize session issuance with administrator status changes.
            # Password verification remains outside the transaction, but neither
            # that old status nor an old password hash can authorize a session.
            current = repository.lock_credentials(cur, row["id"])
            if current is None or current["password_hash"] != row["password_hash"]:
                _record_failure(cur, key)
                outcome = InvalidCredentials()
            elif current["status"] != "active":
                outcome = DisabledAccount()
            else:
                repository.clear_throttle(cur, key)
                repository.mark_login(cur, row["id"])
                token = _create_session(cur, row["id"])
                outcome = None
    if outcome is not None:
        raise outcome
    return token


def _create_session(cur: Any, user_id: str) -> str:
    token = security.new_session_token()
    repository.create_session(cur, str(uuid.uuid4()), user_id, security.hash_secret(token), config.SESSION_TTL_MINUTES)
    return token


def current_user(token: str) -> User | None:
    if not token:
        return None
    with session.read_session() as cur:
        row = repository.current_user(cur, security.hash_secret(token))
    return User(id=row["id"], email=row["email"], is_admin=bool(row["is_admin"])) if row else None


def logout(token: str) -> None:
    if not token:
        return
    with session.unit_of_work() as cur:
        repository.revoke_session(cur, security.hash_secret(token))

"""账号注册、登录、会话与登录限速。归属认定只来自服务端会话，不信任客户端提交。"""

from __future__ import annotations

import datetime
import re
import uuid
from dataclasses import dataclass
from typing import Any

import pymysql

from app.core import config, security
from app.db import session

_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def normalize_email(email: str) -> str:
    # 仅去首尾空白并转小写；按需求不合并点号、加号或重音别名。
    return email.strip().lower()


def valid_email_shape(email: str) -> bool:
    return bool(email) and len(email) <= config.EMAIL_MAX and bool(_EMAIL_SHAPE.match(email))


def _throttle_key(normalized_email: str, source: str) -> str:
    return f"{normalized_email}|{source}"


def _select_user(cur: Any, normalized_email: str) -> dict[str, Any] | None:
    cur.execute(
        "SELECT id, email, password_hash, status FROM users"
        " WHERE email_normalized = %s",
        (normalized_email,),
    )
    return cur.fetchone()


def _locked(cur: Any, key: str) -> bool:
    cur.execute(
        "SELECT locked_until FROM login_throttle WHERE throttle_key = %s", (key,)
    )
    row = cur.fetchone()
    return bool(row and row["locked_until"] and row["locked_until"] > utc_now())


def _record_failure(cur: Any, key: str) -> None:
    """并发安全计数：一条 UPSERT 完成读改写，行锁由语句自身持有。

    先查后改会丢并发失败计数（5 次只记 2 次），首次并发插入还会撞主键；
    先 INSERT 再 SELECT ... FOR UPDATE 的写法在 INSERT IGNORE 下会死锁。
    窗口过期则重新从 1 计数，达到阈值才写 locked_until。
    """
    now = utc_now()
    window_seconds = config.FAILED_WINDOW_MINUTES * 60
    reset = "TIMESTAMPDIFF(SECOND, first_failed_at, %s) > %s"
    next_count = f"IF({reset}, 1, failed_count + 1)"
    # SET 从左到右求值，且后面对同一列的引用会读到刚写入的新值：
    # locked_until 必须排在 failed_count 之前，才能按自增前的旧值判阈值。
    cur.execute(
        "INSERT INTO login_throttle (throttle_key, failed_count, first_failed_at,"
        " locked_until, updated_at) VALUES (%s, 1, %s, NULL, %s)"
        " ON DUPLICATE KEY UPDATE"
        f" locked_until = IF({next_count} >= %s, %s, NULL),"
        f" failed_count = {next_count},"
        f" first_failed_at = IF({reset}, %s, first_failed_at),"
        " updated_at = %s",
        (
            key, now, now,
            now, window_seconds, config.MAX_FAILED_ATTEMPTS,
            now + datetime.timedelta(minutes=config.LOCK_MINUTES),
            now, window_seconds,
            now, window_seconds, now,
            now,
        ),
    )


def register_user(email: str, password: str) -> User:
    normalized = normalize_email(email)
    try:
        with session.transaction() as cur:
            cur.execute(
                "INSERT INTO users (id, email, email_normalized, password_hash, status,"
                " created_at, updated_at)"
                " VALUES (%s, %s, %s, %s, 'active', UTC_TIMESTAMP(3), UTC_TIMESTAMP(3))",
                (
                    str(uuid.uuid4()),
                    email.strip(),
                    normalized,
                    security.hash_password(password),
                ),
            )
    except pymysql.err.IntegrityError:
        raise EmailAlreadyRegistered() from None
    return _fetch_user(normalized)


def _fetch_user(normalized: str) -> User:
    with session.cursor() as cur:
        row = _select_user_by_normalized(cur, normalized)
    return User(id=row["id"], email=row["email"], is_admin=bool(row["is_admin"]))


def _select_user_by_normalized(cur: Any, normalized: str) -> dict[str, Any] | None:
    cur.execute(
        "SELECT id, email, is_admin FROM users WHERE email_normalized = %s", (normalized,)
    )
    return cur.fetchone()


def login(email: str, password: str, source: str) -> str:
    """校验凭据并签发会话，返回明文会话 Token；失败抛出 AuthError。"""
    normalized = normalize_email(email)
    key = _throttle_key(normalized, source)

    # 口令验证开销较大，先在不持有写事务的读取中完成，再用短事务落终态。
    with session.cursor() as cur:
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
    with session.transaction() as cur:
        if not authenticated:
            _record_failure(cur, key)
            outcome = InvalidCredentials()
        elif _locked(cur, key):
            outcome = AccountLocked()
        else:
            # Serialize session issuance with administrator status changes.
            # Password verification remains outside the transaction, but neither
            # that old status nor an old password hash can authorize a session.
            cur.execute(
                "SELECT id, password_hash, status FROM users WHERE id = %s FOR UPDATE",
                (row["id"],),
            )
            current = cur.fetchone()
            if current is None or current["password_hash"] != row["password_hash"]:
                _record_failure(cur, key)
                outcome = InvalidCredentials()
            elif current["status"] != "active":
                outcome = DisabledAccount()
            else:
                cur.execute("DELETE FROM login_throttle WHERE throttle_key = %s", (key,))
                cur.execute(
                    "UPDATE users SET last_login_at = UTC_TIMESTAMP(3),"
                    " updated_at = UTC_TIMESTAMP(3) WHERE id = %s",
                    (row["id"],),
                )
                token = _create_session(cur, row["id"])
                outcome = None
    if outcome is not None:
        raise outcome
    return token


def _create_session(cur: Any, user_id: str) -> str:
    token = security.new_session_token()
    cur.execute(
        "INSERT INTO user_sessions (id, user_id, token_hash, created_at, expires_at)"
        " VALUES (%s, %s, %s, UTC_TIMESTAMP(3), DATE_ADD(UTC_TIMESTAMP(3), INTERVAL %s MINUTE))",
        (
            str(uuid.uuid4()),
            user_id,
            security.hash_secret(token),
            config.SESSION_TTL_MINUTES,
        ),
    )
    return token


def current_user(token: str) -> User | None:
    if not token:
        return None
    with session.cursor() as cur:
        cur.execute(
            "SELECT u.id, u.email, u.is_admin FROM user_sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash = %s AND s.revoked_at IS NULL"
            " AND s.expires_at > UTC_TIMESTAMP(3) AND u.status = 'active'",
            (security.hash_secret(token),),
        )
        row = cur.fetchone()
    return User(id=row["id"], email=row["email"], is_admin=bool(row["is_admin"])) if row else None


def logout(token: str) -> None:
    if not token:
        return
    with session.cursor() as cur:
        cur.execute(
            "UPDATE user_sessions SET revoked_at = UTC_TIMESTAMP(3)"
            " WHERE token_hash = %s AND revoked_at IS NULL",
            (security.hash_secret(token),),
        )

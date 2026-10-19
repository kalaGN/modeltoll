"""显式初始化首个管理员；不提升已有普通用户，不重置任何已有口令。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core import config, security, validation
from app.db import session
from app.repositories import accounts as repository

class BootstrapError(Exception):
    """对运维可展示的固定错误，不包含连接信息、密码或底层异常。"""


@dataclass(frozen=True)
class BootstrapResult:
    id: str
    email: str
    created: bool


def init_admin(email: str, password: str) -> BootstrapResult:
    if not isinstance(email, str):
        raise BootstrapError("邮箱格式不正确")
    normalized = validation.normalize_email(email)
    if any(c in email for c in "\r\n") or not validation.valid_email_shape(normalized):
        raise BootstrapError("邮箱格式不正确")
    if not isinstance(password, str) or not config.PASSWORD_MIN <= len(password) <= config.PASSWORD_MAX:
        raise BootstrapError(f"密码长度须为 {config.PASSWORD_MIN}–{config.PASSWORD_MAX} 个字符")

    # Hashing is deliberately outside database transactions and the named lock.
    # The locked recheck below remains authoritative if the account changes here.
    with session.read_session() as db:
        existing = repository.bootstrap_user(db, normalized)
    password_hash = security.hash_password(password) if existing is None else None

    with session.pinned_session() as db:
        acquired = False
        committed = False
        try:
            if not repository.bootstrap_lock(db):
                raise BootstrapError("管理员初始化锁不可用，请稍后重试")
            acquired = True
            # GET_LOCK is a SELECT and triggers SQLAlchemy autobegin. End that
            # transaction, keeping the same physical connection and named lock.
            db.rollback()
            with db.begin():
                user = repository.bootstrap_user(db, normalized, lock=True)
                if user:
                    if not user["is_admin"]:
                        raise BootstrapError("邮箱已属于普通用户，初始化不会自动提升权限")
                    if user["status"] != "active":
                        raise BootstrapError("该管理员已停用，初始化不会自动激活")
                    result = BootstrapResult(user["id"], user["email"], False)
                else:
                    if repository.any_admin(db):
                        raise BootstrapError("平台已有管理员，不能再初始化首个管理员")
                    if password_hash is None:
                        # User deletion is not a supported operation. Do not hash
                        # while holding a transaction if an external writer did it.
                        raise BootstrapError("账号状态已变化，请重新执行初始化")
                    user_id = str(uuid.uuid4())
                    repository.create_admin(db, user_id, normalized, password_hash)
                    result = BootstrapResult(user_id, normalized, True)
            committed = True
        finally:
            if acquired:
                try:
                    if not repository.bootstrap_lock(db, release=True):
                        raise BootstrapError("初始化锁释放未确认，请重复执行检查结果")
                except Exception:
                    # Closing the pinned connection still releases its named lock.
                    # Preserve original failures; never claim success after a lost
                    # release acknowledgement following a committed creation.
                    if committed:
                        raise BootstrapError("初始化锁释放未确认，请重复执行检查结果") from None
        return result

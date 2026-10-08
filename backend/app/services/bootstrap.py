"""显式初始化首个管理员；不提升已有普通用户，不重置任何已有口令。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core import config, security
from app.db import session
from app.services import accounts

# 按当前数据库隔离，摘要后总长度为 55，符合 MySQL 命名锁 64 字符上限。
_LOCK_NAME_SQL = "CONCAT('laya:init-admin:', LEFT(SHA2(DATABASE(), 256), 40))"
_LOCK_TIMEOUT_SECONDS = 10


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
    normalized = accounts.normalize_email(email)
    if any(c in email for c in "\r\n") or not accounts.valid_email_shape(normalized):
        raise BootstrapError("邮箱格式不正确")
    if not isinstance(password, str) or not config.PASSWORD_MIN <= len(password) <= config.PASSWORD_MAX:
        raise BootstrapError(f"密码长度须为 {config.PASSWORD_MIN}–{config.PASSWORD_MAX} 个字符")

    conn = session._new_connection(autocommit=False)
    try:
        with conn.cursor() as cur:
            acquired = False
            committed = False
            try:
                cur.execute(f"SELECT GET_LOCK({_LOCK_NAME_SQL}, %s) AS acquired", (_LOCK_TIMEOUT_SECONDS,))
                row = cur.fetchone()
                if not row or row["acquired"] != 1:
                    raise BootstrapError("管理员初始化锁不可用，请稍后重试")
                acquired = True
                conn.begin()
                try:
                    cur.execute(
                        "SELECT id, email, status, is_admin FROM users"
                        " WHERE email_normalized = %s FOR UPDATE", (normalized,),
                    )
                    user = cur.fetchone()
                    if user:
                        if not user["is_admin"]:
                            raise BootstrapError("邮箱已属于普通用户，初始化不会自动提升权限")
                        if user["status"] != "active":
                            raise BootstrapError("该管理员已停用，初始化不会自动激活")
                        result = BootstrapResult(user["id"], user["email"], False)
                    else:
                        # 停用管理员也算已初始化，不能通过新邮箱绕过此限制。
                        cur.execute("SELECT id FROM users WHERE is_admin = 1 LIMIT 1 FOR UPDATE")
                        if cur.fetchone():
                            raise BootstrapError("平台已有管理员，不能再初始化首个管理员")
                        user_id = str(uuid.uuid4())
                        password_hash = security.hash_password(password)
                        cur.execute(
                            "INSERT INTO users (id, email, email_normalized, password_hash, status,"
                            " is_admin, created_at, updated_at)"
                            " VALUES (%s, %s, %s, %s, 'active', 1, UTC_TIMESTAMP(3), UTC_TIMESTAMP(3))",
                            (user_id, normalized, normalized, password_hash),
                        )
                        result = BootstrapResult(user_id, normalized, True)
                    conn.commit()
                    committed = True
                except BaseException:
                    conn.rollback()
                    raise
            finally:
                if acquired:
                    try:
                        cur.execute(f"SELECT RELEASE_LOCK({_LOCK_NAME_SQL}) AS released")
                        row = cur.fetchone()
                        if not row or row["released"] != 1:
                            raise BootstrapError("初始化锁释放未确认，请重复执行检查结果")
                    except Exception:
                        # 关闭连接仍释放连接级命名锁。保留原操作异常；已提交时
                        # 不返回伪成功，提示重跑确认（幂等且不会改密码）。
                        if committed:
                            raise BootstrapError("初始化锁释放未确认，请重复执行检查结果") from None
            return result
    finally:
        conn.close()

"""API Key 生命周期与推理鉴权。库里只存 SHA-256，完整秘密仅创建时返回一次。"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import Any

from app.core import security
from app.core.time import iso_utc
from app.db import session
from app.repositories import api_keys as repository
from app.core.time import utc_now


class ApiKeyError(Exception):
    status_code = 400
    code = "api_key_error"
    message = "API Key 操作失败"


class InvalidApiKey(ApiKeyError):
    status_code = 401
    code = "invalid_api_key"
    message = "API Key 缺失、无效或已撤销"


class DisabledAccountKey(ApiKeyError):
    status_code = 403
    code = "account_disabled"
    message = "账号已停用"


class ApiKeyNotFound(ApiKeyError):
    status_code = 404
    code = "api_key_not_found"
    message = "API Key 不存在"


class ApiKeyNotRevoked(ApiKeyError):
    status_code = 409
    code = "api_key_not_revoked"
    message = "请先撤销 API Key，再删除"


@dataclass(frozen=True)
class Principal:
    """通过 Key 鉴权后的可信归属；推理与统计只使用它，不接受客户端声明。"""

    user_id: str
    api_key_id: str
    display: str


@dataclass(frozen=True)
class ApiKeyRecord:
    id: str
    name: str
    display: str
    status: str
    created_at: datetime.datetime
    last_used_at: datetime.datetime | None
    revoked_at: datetime.datetime | None

    @property
    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "display": self.display,
            "status": self.status,
            "created_at": iso_utc(self.created_at),
            "last_used_at": iso_utc(self.last_used_at),
            "revoked_at": iso_utc(self.revoked_at),
        }


def _record(row: dict[str, Any]) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=row["id"],
        name=row["name"],
        display=security.masked_key(row["display_prefix"], row["last_four"]),
        status="revoked" if row["revoked_at"] else "active",
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        revoked_at=row["revoked_at"],
    )


def _fetch(key_id: str) -> dict[str, Any]:
    with session.read_session() as db:
        return repository.fetch(db, key_id)


def create(user_id: str, name: str = "") -> tuple[ApiKeyRecord, str]:
    secret, prefix, last_four = security.new_api_key()
    key_id = str(uuid.uuid4())
    with session.unit_of_work() as db:
        repository.create(db, key_id, user_id, name, security.hash_secret(secret), prefix, last_four)
    return _fetch_record(key_id), secret


def _fetch_record(key_id: str) -> ApiKeyRecord:
    return _record(_fetch(key_id))


def list_for_user(user_id: str) -> list[ApiKeyRecord]:
    with session.read_session() as db:
        rows = repository.list_for_user(db, user_id)
    return [_record(row) for row in rows]


def revoke(user_id: str, key_id: str) -> ApiKeyRecord:
    """只撤销本人 Key；跨用户与不存在返回同一个 404，不泄露存在性。"""
    with session.unit_of_work() as db:
        if repository.revoke(db, user_id, key_id) == 0 and not repository.visible_owned_key(db, user_id, key_id):
            raise ApiKeyNotFound()
    return _fetch_record(key_id)


def delete(user_id: str, key_id: str) -> None:
    """仅隐藏本人已撤销 Key；原始行保留以维持历史调用与费用关联。"""
    with session.unit_of_work() as db:
        if repository.soft_delete(db, user_id, key_id):
            return
        record = repository.owned_state(db, user_id, key_id)
        if record is None:
            raise ApiKeyNotFound()
        if record["revoked_at"] is None:
            raise ApiKeyNotRevoked()
        # 已删除时幂等成功；若刚好与撤销并发，则重新由客户端发起删除。
        if record["deleted_at"] is None:
            raise ApiKeyNotRevoked()


def authenticate(authorization: str) -> Principal:
    if not authorization.startswith("Bearer "):
        raise InvalidApiKey()
    raw = authorization[len("Bearer ") :].strip()
    if not raw:
        raise InvalidApiKey()
    with session.read_session() as db:
        row = repository.authenticate(db, security.hash_secret(raw))
    if row is None:
        raise InvalidApiKey()
    if row["status"] != "active":
        raise DisabledAccountKey()
    return Principal(
        user_id=row["user_id"],
        api_key_id=row["id"],
        display=security.masked_key(row["display_prefix"], row["last_four"]),
    )


def still_valid(api_key_id: str) -> bool:
    """拿到推理锁后重新检查撤销与账号状态，避免排队期间失效的 Key 继续推理。"""
    with session.read_session() as db:
        return repository.still_valid(db, api_key_id)


def mark_used(api_key_id: str, at: datetime.datetime | None = None) -> None:
    with session.unit_of_work() as db:
        repository.mark_used(db, api_key_id, at or utc_now())

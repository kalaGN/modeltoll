"""密码与秘密哈希。口令用 Argon2id 自描述哈希；高熵随机 Token 用 SHA-256。"""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core import config

_hasher = PasswordHasher(
    time_cost=config.ARGON2_TIME_COST,
    memory_cost=config.ARGON2_MEMORY_COST_KIB,
    parallelism=config.ARGON2_PARALLELISM,
    hash_len=config.ARGON2_HASH_LEN,
    salt_len=config.ARGON2_SALT_LEN,
)

# 账号不存在时也执行一次等量开销的验证，避免用响应时间区分账号是否存在。
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(24))


def dummy_hash() -> str:
    return _DUMMY_HASH


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def hash_secret(secret: str) -> str:
    """会话与 API Key 这类高熵随机值的存储摘要，不用于口令。"""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_api_key() -> tuple[str, str, str]:
    """生成 API Key，返回 (完整秘密, 展示前缀, 末四位)。完整值只返回一次。"""
    secret = f"{config.API_KEY_PREFIX}{secrets.token_urlsafe(config.API_KEY_ENTROPY_BYTES)}"
    return secret, secret[: config.API_KEY_DISPLAY_PREFIX], secret[-4:]


def masked_key(display_prefix: str, last_four: str) -> str:
    """列表与统计里的脱敏标识，不含可认证部分。"""
    return f"{display_prefix}****{last_four}"


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(cookie_value: str, header_value: str) -> bool:
    if not cookie_value or not header_value:
        return False
    return secrets.compare_digest(cookie_value, header_value)

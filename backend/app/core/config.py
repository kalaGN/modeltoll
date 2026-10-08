"""环境配置与会话/安全参数。秘密值只从 .env 或环境变量读取，不写日志。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
FRONTEND_DIST = PROJECT_DIR / "frontend" / "dist"

SUPPORTED_DEVICES = {"mps", "cpu"}

SESSION_COOKIE = "laya_session"
CSRF_COOKIE = "laya_csrf"
SESSION_TTL_MINUTES = 7 * 24 * 60

MAX_FAILED_ATTEMPTS = 5
FAILED_WINDOW_MINUTES = 15
LOCK_MINUTES = 15

PASSWORD_MIN = 8
PASSWORD_MAX = 128
EMAIL_MAX = 254

ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST_KIB = 64 * 1024
ARGON2_PARALLELISM = 4
ARGON2_HASH_LEN = 32
ARGON2_SALT_LEN = 16

# API Key：≥256 位随机熵，只在创建响应中出现一次；库里只存 SHA-256。
API_KEY_PREFIX = "laya_sk_"
API_KEY_ENTROPY_BYTES = 32
API_KEY_DISPLAY_PREFIX = 12

# 已确认定价 1 元 / 1,000,000 输入 Token；入账资格为本次采用值，见任务文档。
BILLING_POLICY_VERSION = "succeeded_only_v1"
PRICING_AMOUNT_EXPONENT = Decimal("0.000001")

# 分页与统计窗口上限；默认窗口是采用值，产品未确认前不视为长期契约。
PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100
STATS_DEFAULT_DAYS = 30


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


def read_env_file() -> dict[str, str]:
    """解析根目录 .env；真实环境变量优先于文件，便于启动器覆盖。"""
    values: dict[str, str] = {}
    env_file = PROJECT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    values.update({k: v for k, v in os.environ.items() if k.startswith("MYSQL_") and v})
    return values


def database_config() -> DatabaseConfig:
    env = read_env_file()
    missing = [
        key
        for key in ("MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE")
        if not env.get(key)
    ]
    if missing:
        raise RuntimeError(
            f"缺少数据库配置: {', '.join(missing)}；请在项目根目录 .env 中提供"
        )
    return DatabaseConfig(
        host=env.get("MYSQL_HOST", "127.0.0.1"),
        port=int(env.get("MYSQL_PORT", "3306")),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
    )


def laya_device() -> str:
    device = os.environ.get("LAYA_DEVICE", "mps")
    if device not in SUPPORTED_DEVICES:
        raise ValueError("LAYA_DEVICE 只支持 mps 或 cpu")
    return device


def configure_model_cache() -> None:
    # Laya 在导入时读取 HF_HOME，必须在加载模型前设置且保持离线。
    os.environ.setdefault("HF_HOME", str(PROJECT_DIR / ".hf-cache"))


def laya_runtime() -> str:
    runtime = os.environ.get('LAYA_RUNTIME', 'local')
    if runtime not in {'local', 'external'}:
        raise ValueError('LAYA_RUNTIME 只支持 local 或 external')
    return runtime

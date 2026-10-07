"""表结构。DDL 唯一来源是 backend/migrations/*.sql，此处只负责执行。"""

from __future__ import annotations

from pathlib import Path

from app.core import config
from app.db import session

# 按依赖顺序：账号/会话 → Key → 价格与调用/费用。回滚脚本同名 *_rollback.sql。
MIGRATIONS = ("0001_auth.sql", "0002_api_keys.sql", "0003_billing.sql", "0004_api_key_deletion.sql")


def statements(sql_file: Path) -> list[str]:
    """按行尾分号切分语句；DDL 与种子数据内不含字符串字面量分号，注释行忽略。"""
    body = [
        line
        for line in sql_file.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("--")
    ]
    return [chunk.strip() for chunk in "\n".join(body).split(";") if chunk.strip()]


def init_db() -> None:
    # MySQL 的 DDL 隐式提交；迁移通过 IF NOT EXISTS 或元数据检查允许重复执行。
    with session.cursor() as cur:
        for name in MIGRATIONS:
            for statement in statements(config.MIGRATIONS_DIR / name):
                cur.execute(statement)

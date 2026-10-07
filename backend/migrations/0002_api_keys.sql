-- Laya 平台迁移 0002：模型调用密钥
-- 依据 docs/20261002-Laya平台-设计.md §5。状态由 revoked_at 推导，不存明文 Key。
-- name 是 2026-10-03 用户新增的展示用名称，设计 §5 原把命名列为「暂不加列」。
-- 回滚脚本见 0002_api_keys_rollback.sql。

CREATE TABLE IF NOT EXISTS api_keys (
  id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name VARCHAR(60) NOT NULL DEFAULT '',
  key_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  display_prefix VARCHAR(32) NOT NULL,
  last_four CHAR(4) NOT NULL,
  created_at DATETIME(3) NOT NULL,
  last_used_at DATETIME(3) NULL,
  revoked_at DATETIME(3) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_api_keys_hash (key_hash),
  UNIQUE KEY uk_api_keys_id_user (id, user_id),
  KEY idx_api_keys_user_created (user_id, created_at, id),
  CONSTRAINT fk_api_keys_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

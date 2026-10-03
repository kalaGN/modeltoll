-- Laya 平台迁移 0001：邮箱账号、登录会话与登录限速
-- 目标数据库：MySQL 8.0+ / 9.x（InnoDB, utf8mb4）
-- 依据 docs/20261002-Laya平台-设计.md §3、§4；login_throttle 为 §4 要求的
-- 按账号+来源限速计数，设计文档未列具体表，本次实现补齐并记录于任务文档。
-- 时间统一存 UTC naive DATETIME(3)，由 UTC_TIMESTAMP(3) 写入。
-- 回滚脚本见 0001_auth_rollback.sql。

CREATE TABLE IF NOT EXISTS users (
  id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  email VARCHAR(254) NOT NULL,
  email_normalized VARCHAR(254)
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'active',
  last_login_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_users_email_normalized (email_normalized),
  CONSTRAINT chk_users_status CHECK (status IN ('active', 'disabled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS user_sessions (
  id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  created_at DATETIME(3) NOT NULL,
  expires_at DATETIME(3) NOT NULL,
  revoked_at DATETIME(3) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_sessions_token_hash (token_hash),
  KEY idx_sessions_user (user_id, revoked_at),
  KEY idx_sessions_expires (expires_at),
  CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS login_throttle (
  throttle_key VARCHAR(300)
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs NOT NULL,
  failed_count INT UNSIGNED NOT NULL DEFAULT 0,
  first_failed_at DATETIME(3) NOT NULL,
  locked_until DATETIME(3) NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (throttle_key),
  KEY idx_throttle_locked (locked_until)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

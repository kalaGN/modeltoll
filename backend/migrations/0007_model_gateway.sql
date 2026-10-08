-- 单行上游配置。凭据仅从环境读取。
CREATE TABLE IF NOT EXISTS model_connection (
  id TINYINT UNSIGNED NOT NULL,
  base_url VARCHAR(512) NOT NULL,
  model VARCHAR(64) NOT NULL,
  timeout_seconds SMALLINT UNSIGNED NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 0,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT chk_connection_singleton CHECK (id = 1),
  CONSTRAINT chk_connection_timeout CHECK (timeout_seconds BETWEEN 1 AND 300)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

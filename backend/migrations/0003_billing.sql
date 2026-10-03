-- Laya 平台迁移 0003：价格版本、调用明细与费用明细
-- 依据 docs/20261002-Laya平台-设计.md §6、§7、§8。
-- pricing_rules 与 usage_charges 只追加不改写；api_calls 用复合外键保证
-- user_id 与 api_key_id 归属一致。时间统一存 UTC naive DATETIME(3)。
-- 回滚脚本见 0003_billing_rollback.sql。

CREATE TABLE IF NOT EXISTS pricing_rules (
  id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version VARCHAR(32) NOT NULL,
  model VARCHAR(64) NOT NULL,
  currency CHAR(3) NOT NULL,
  token_basis VARCHAR(32) NOT NULL,
  unit_tokens BIGINT UNSIGNED NOT NULL,
  unit_price_yuan DECIMAL(20,6) NOT NULL,
  billing_policy_version VARCHAR(32) NOT NULL,
  effective_from DATETIME(3) NOT NULL,
  created_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_pricing_version (version),
  UNIQUE KEY uk_pricing_model_effective (model, effective_from),
  CONSTRAINT chk_pricing_unit_tokens CHECK (unit_tokens > 0),
  CONSTRAINT chk_pricing_price CHECK (unit_price_yuan >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 已确认定价：1 元 / 1,000,000 输入 Token（需求 R05/R06）。
-- billing_policy_version 记录本次采用的入账资格，见任务文档。
INSERT IGNORE INTO pricing_rules (
  id, version, model, currency, token_basis, unit_tokens, unit_price_yuan,
  billing_policy_version, effective_from, created_at
) VALUES (
  '00000000-0000-0000-0000-000000000001', 'v1', 'multilingual', 'CNY',
  'laya_usage_input_tokens', 1000000, 1.000000, 'succeeded_only_v1',
  '2026-01-01 00:00:00.000', UTC_TIMESTAMP(3)
);

CREATE TABLE IF NOT EXISTS api_calls (
  id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  api_key_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  endpoint VARCHAR(128) NOT NULL,
  model VARCHAR(64) NOT NULL,
  model_revision VARCHAR(128) NULL,
  pricing_rule_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  status VARCHAR(24) NOT NULL,
  http_status SMALLINT NULL,
  error_code VARCHAR(64) NULL,
  started_at DATETIME(3) NOT NULL,
  completed_at DATETIME(3) NULL,
  duration_ms BIGINT UNSIGNED NULL,
  input_tokens BIGINT UNSIGNED NULL,
  output_tokens BIGINT UNSIGNED NULL,
  truncated TINYINT(1) NULL,
  state_tokens_dropped BIGINT UNSIGNED NULL,
  billing_status VARCHAR(16) NOT NULL,
  billing_reason VARCHAR(64) NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_calls_user_started (user_id, started_at, id),
  KEY idx_calls_key_started (user_id, api_key_id, started_at, id),
  KEY idx_calls_endpoint_started (user_id, endpoint, started_at, id),
  KEY idx_calls_billing (billing_status, started_at),
  CONSTRAINT fk_calls_key_user FOREIGN KEY (api_key_id, user_id)
    REFERENCES api_keys (id, user_id),
  CONSTRAINT fk_calls_pricing FOREIGN KEY (pricing_rule_id)
    REFERENCES pricing_rules (id),
  CONSTRAINT chk_calls_status CHECK (
    status IN ('accepted', 'running', 'succeeded', 'failed', 'interrupted')
  ),
  CONSTRAINT chk_calls_billing_status CHECK (
    billing_status IN ('pending', 'charged', 'not_billable')
  ),
  CONSTRAINT chk_calls_completed CHECK (
    status IN ('accepted', 'running') OR completed_at IS NOT NULL
  ),
  CONSTRAINT chk_calls_succeeded_usage CHECK (
    status <> 'succeeded' OR input_tokens IS NOT NULL
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS usage_charges (
  id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  call_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  pricing_rule_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  billable_input_tokens BIGINT UNSIGNED NOT NULL,
  unit_tokens BIGINT UNSIGNED NOT NULL,
  unit_price_yuan DECIMAL(20,6) NOT NULL,
  amount_yuan DECIMAL(20,6) NOT NULL,
  currency CHAR(3) NOT NULL,
  created_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_charges_call (call_id),
  KEY idx_charges_created (created_at, id),
  CONSTRAINT fk_charges_call FOREIGN KEY (call_id) REFERENCES api_calls (id),
  CONSTRAINT fk_charges_pricing FOREIGN KEY (pricing_rule_id)
    REFERENCES pricing_rules (id),
  CONSTRAINT chk_charges_tokens CHECK (billable_input_tokens >= 0),
  CONSTRAINT chk_charges_unit CHECK (unit_tokens > 0),
  CONSTRAINT chk_charges_amount CHECK (amount_yuan >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Immutable server-side success facts; no prompts, outputs or credentials.
CREATE TABLE IF NOT EXISTS inference_success_receipts (
  call_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  input_tokens BIGINT UNSIGNED NOT NULL,
  output_tokens BIGINT UNSIGNED NULL,
  truncated TINYINT(1) NULL,
  state_tokens_dropped BIGINT UNSIGNED NULL,
  completed_at DATETIME(3) NOT NULL,
  duration_ms BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (call_id),
  CONSTRAINT fk_success_receipt_call FOREIGN KEY (call_id) REFERENCES api_calls (id),
  CONSTRAINT chk_receipt_input CHECK (input_tokens <= 9223372036854775807),
  CONSTRAINT chk_receipt_output CHECK (output_tokens <= 9223372036854775807),
  CONSTRAINT chk_receipt_dropped CHECK (state_tokens_dropped <= 9223372036854775807),
  CONSTRAINT chk_receipt_truncated CHECK (truncated IS NULL OR truncated IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

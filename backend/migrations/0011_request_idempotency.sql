-- Never store plaintext Idempotency-Key or request payloads; no automatic expiry.
CREATE TABLE IF NOT EXISTS request_idempotency (
  user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  key_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  request_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  call_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  created_at DATETIME(3) NOT NULL,
  PRIMARY KEY (user_id, key_hash),
  UNIQUE KEY uk_request_idempotency_call (call_id),
  CONSTRAINT fk_idempotency_user FOREIGN KEY (user_id) REFERENCES users (id),
  CONSTRAINT fk_idempotency_call FOREIGN KEY (call_id) REFERENCES api_calls (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

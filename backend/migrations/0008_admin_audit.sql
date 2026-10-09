-- Administrator audit history: append-only by application convention.
CREATE TABLE IF NOT EXISTS admin_audit_events (
  id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  actor_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  target_user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  target_key_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
  action VARCHAR(32) NOT NULL,
  previous_status VARCHAR(16) NOT NULL,
  new_status VARCHAR(16) NOT NULL,
  reason VARCHAR(200) NOT NULL,
  created_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_admin_audit_created (created_at, id),
  KEY idx_admin_audit_target (target_user_id, created_at, id),
  CONSTRAINT fk_admin_audit_actor FOREIGN KEY (actor_id) REFERENCES users (id),
  CONSTRAINT fk_admin_audit_target FOREIGN KEY (target_user_id) REFERENCES users (id),
  CONSTRAINT fk_admin_audit_key_owner FOREIGN KEY (target_key_id, target_user_id)
    REFERENCES api_keys (id, user_id),
  CONSTRAINT chk_admin_audit_action CHECK (action IN ('user.status_changed', 'api_key.revoked')),
  CONSTRAINT chk_admin_audit_status CHECK (
    (action = 'user.status_changed' AND target_key_id IS NULL
     AND previous_status IN ('active', 'disabled') AND new_status IN ('active', 'disabled')
     AND previous_status <> new_status)
    OR (action = 'api_key.revoked' AND target_key_id IS NOT NULL
        AND previous_status = 'active' AND new_status = 'revoked')),
  CONSTRAINT chk_admin_audit_reason CHECK (CHAR_LENGTH(TRIM(reason)) BETWEEN 1 AND 200)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

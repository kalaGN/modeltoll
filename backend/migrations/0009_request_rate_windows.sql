-- UTC fixed-minute request admission counters, never billing facts.
CREATE TABLE IF NOT EXISTS request_rate_windows (
  user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  window_start DATETIME NOT NULL,
  request_count INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, window_start),
  KEY idx_request_rate_window (window_start),
  CONSTRAINT fk_request_rate_user FOREIGN KEY (user_id) REFERENCES users (id),
  CONSTRAINT chk_request_rate_count CHECK (request_count >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

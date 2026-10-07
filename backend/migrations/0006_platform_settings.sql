-- 平台品牌单行配置；仅保存公开品牌信息，不保存敏感系统配置。
CREATE TABLE IF NOT EXISTS platform_settings (
  id TINYINT NOT NULL PRIMARY KEY,
  name VARCHAR(60) NOT NULL DEFAULT 'Laya',
  description VARCHAR(200) NOT NULL DEFAULT '模型 API 平台',
  logo_blob MEDIUMBLOB NULL,
  logo_mime VARCHAR(32) NULL,
  updated_at DATETIME(3) NOT NULL,
  CONSTRAINT chk_platform_settings_singleton CHECK (id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
INSERT IGNORE INTO platform_settings (id, name, description, updated_at)
VALUES (1, 'Laya', '模型 API 平台', UTC_TIMESTAMP(3));

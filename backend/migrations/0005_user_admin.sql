-- 新增管理员标志；既有账号与公开注册默认普通用户。
SET @laya_admin_ddl = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE, ADD CONSTRAINT chk_users_admin CHECK (is_admin IN (0, 1))',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'users' AND column_name = 'is_admin'
);
PREPARE laya_admin_stmt FROM @laya_admin_ddl;
EXECUTE laya_admin_stmt;
DEALLOCATE PREPARE laya_admin_stmt;

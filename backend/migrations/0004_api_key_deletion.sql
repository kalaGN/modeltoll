-- 已撤销密钥软删除；保留被历史调用与账务引用的 Key 行。
-- MySQL 不支持 ADD COLUMN IF NOT EXISTS，启动时按元数据判断，允许重复执行。
SET @laya_delete_ddl = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE api_keys ADD COLUMN deleted_at DATETIME(3) NULL',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'api_keys' AND column_name = 'deleted_at'
);
PREPARE laya_delete_stmt FROM @laya_delete_ddl;
EXECUTE laya_delete_stmt;
DEALLOCATE PREPARE laya_delete_stmt;

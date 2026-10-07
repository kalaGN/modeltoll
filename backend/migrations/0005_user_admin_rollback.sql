-- 先回滚管理员代码。所有账号仍保留，但失去管理员角色标志。
ALTER TABLE users DROP CONSTRAINT chk_users_admin, DROP COLUMN is_admin;

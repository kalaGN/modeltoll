-- Laya 平台迁移 0001 回滚：删除登录相关表
-- 账单类数据不存在时可安全回滚。users 被 user_sessions 外键引用，按逆序删除。
-- 生产环境有真实账号数据时禁止直接执行，需先备份。

DROP TABLE IF EXISTS login_throttle;
DROP TABLE IF EXISTS user_sessions;
DROP TABLE IF EXISTS users;

-- Laya 平台回滚 0002：删除 API Key 表。
-- 警告：仅在确认无历史调用引用这些 Key 且允许丢失数据时执行；
-- 有账单或调用记录时禁止直接回滚（设计 §10）。

DROP TABLE IF EXISTS api_keys;

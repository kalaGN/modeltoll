-- Laya 平台回滚 0002：删除 API Key 表。
-- 警告：仅在确认无历史调用引用这些 Key 且允许丢失数据时执行；
-- 有账单或调用记录时禁止直接回滚（设计 §10）。
-- 若只想回滚 2026-10-03 新增的展示名称列，用
--   ALTER TABLE api_keys DROP COLUMN name;
-- 该列由 ALTER 加到已存在的表上，CREATE TABLE IF NOT EXISTS 不会自动补齐，
-- 新库直接由本文件的 DDL 建表即含此列。

DROP TABLE IF EXISTS api_keys;

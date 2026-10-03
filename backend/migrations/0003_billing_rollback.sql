-- Laya 平台回滚 0003：删除费用、调用与价格表。
-- 警告：账单表禁止在有真实数据的环境直接回滚（设计 §10）；
-- 此脚本只用于确认可以清空的本机验证库，执行前必须逐条确认。

DROP TABLE IF EXISTS usage_charges;
DROP TABLE IF EXISTS api_calls;
DROP TABLE IF EXISTS pricing_rules;

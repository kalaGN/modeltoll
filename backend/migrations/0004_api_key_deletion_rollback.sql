-- 先撤回依赖 deleted_at 的代码再执行；已隐藏 Key 将重新出现在列表，但保持撤销状态。
-- 不删除任何历史调用或费用。仅在明确授权回滚时执行。
ALTER TABLE api_keys DROP COLUMN deleted_at;

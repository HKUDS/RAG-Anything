-- 025_remove_user_email.sql — 移除用户邮箱系统：users.email 全链路下线。
-- 登录/注册仅使用 username + password；PG 会随列自动删除唯一索引 idx_users_email；
-- 历史邮箱数据不可恢复。
BEGIN;

ALTER TABLE users DROP COLUMN IF EXISTS email;

COMMIT;

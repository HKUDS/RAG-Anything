## 1. Brute-Force Protection Fix

- [x] 1.1 Change `record_failed_login()` signature from `username: str` to `user_id: int` in `raganything/services/auth.py`
- [x] 1.2 Change SQL in `record_failed_login()` from `WHERE username = ?` to `WHERE id = ?`
- [x] 1.3 Change `reset_failed_logins()` signature from `username: str` to `user_id: int` and SQL to `WHERE id = ?`
- [x] 1.4 Change `check_account_locked()` signature from `username: str` to `user_id: int` and SQL to `WHERE id = ?`
- [x] 1.5 Fix call site in `raganything/routers/auth.py` line 99: pass `user["id"]` (now correct type)
- [x] 1.6 Fix call site in `raganything/routers/auth.py` line 102: pass `user["id"]` (now correct type)
- [x] 1.7 Fix call site in `raganything/dependencies.py` line 68: `check_account_locked(user_id)` now correct type; add error handling for returned lock message
- [x] 1.8 Fix call site in `raganything/routers/auth.py` line 91: change from `req.username` to `user["id"]` for consistency
- [x] 1.9 Add integration test: 6 failed logins locks account, 7th returns 403
- [x] 1.10 Add integration test: locked account's valid JWT is rejected by `get_current_user()`

## 2. Secure Default Admin

- [x] 2.1 Remove hardcoded `"admin123"` fallback from `DEFAULT_ADMIN_PASSWORD` in `raganything/services/auth.py`
- [x] 2.2 Add random password generation (`secrets.token_urlsafe(16)`) when env var is unset
- [x] 2.3 Set `must_change_password = 1` in admin user INSERT in `init_db()`
- [x] 2.4 Print generated password to stderr with clear formatting on first startup
- [ ] 2.5 Remove `.env` from git tracking: `git rm --cached .env`
- [x] 2.6 Update `.env.example` to document `DEFAULT_ADMIN_PASSWORD` without a real value
- [x] 2.7 Add test: fresh install creates admin with `must_change_password=1`

## 3. Complete `init_db()` Schema

- [x] 3.1 Add `CREATE TABLE IF NOT EXISTS roles` to `init_db()`
- [x] 3.2 Add `CREATE TABLE IF NOT EXISTS audit_logs` to `init_db()`
- [x] 3.3 Add default role seeding (admin/editor/viewer INSERT OR IGNORE) to `init_db()`
- [x] 3.4 Add `ALTER TABLE users ADD COLUMN role_id` with try/except guard to `init_db()`
- [x] 3.5 Add `ALTER TABLE users ADD COLUMN last_login_at` with try/except guard
- [x] 3.6 Add `ALTER TABLE users ADD COLUMN must_change_password` with try/except guard
- [x] 3.7 Add audit log indexes (`idx_audit_actor`, `idx_audit_action`, `idx_audit_created`)
- [x] 3.8 Update `scripts/migrate_to_rbac.py` to be idempotent (no-op if tables exist)
- [x] 3.9 Add test: fresh install with empty DB has all required tables after `init_db()`

## 4. Audit Log Integrity

- [x] 4.1 Move `self._queue.clear()` in `_flush()` to AFTER successful `conn.commit()`
- [x] 4.2 Replace `except Exception: pass` with structured ERROR logging + queue retention for retry
- [x] 4.3 Add `consecutive_failures` counter and `_max_queue_size` guard
- [x] 4.4 Add `shutdown()` call in `server.py` shutdown event
- [x] 4.5 Add `GET /admin/health/audit` endpoint exposing queue depth and failure count
- [x] 4.6 Add test: audit write failure retains entries in queue and logs error

## 5. Token Revocation

- [x] 5.1 Add `CREATE TABLE IF NOT EXISTS token_revocations` to `init_db()`
- [x] 5.2 Modify `TokenBlacklist.revoke()` to also persist to SQLite
- [x] 5.3 Modify `TokenBlacklist.is_revoked()` to check SQLite (with in-memory cache)
- [x] 5.4 Add `_load_persisted()` method to reload non-expired revocations on startup
- [x] 5.5 Add periodic `_cleanup()` to delete expired entries from SQLite
- [x] 5.6 Fix `logout()` to accept optional `refresh_token` in request body
- [x] 5.7 Extract `rfam` from refresh token and call `revoke_refresh_family()`
- [x] 5.8 Update `AuthContext.jsx` frontend to send `refresh_token` in logout body
- [x] 5.9 Add test: logout with refresh token → refresh token rejected
- [x] 5.10 Add test: revoke token → restart server → token still rejected

## 6. RBAC Authorization Cleanup

- [x] 6.1 Add `"role_id"` to `allowed_fields` in `update_user()` (`services/auth.py`)
- [x] 6.2 Remove `is_admin` boolean shortcut from `require_permission()` (`dependencies.py`)
- [x] 6.3 Remove deprecated `is_admin` column fallback from `get_current_user()` (`dependencies.py`)
- [x] 6.4 Remove `is_admin` parameter from `create_token()` and `create_refresh_token()`
- [x] 6.5 Remove `is_admin` from JWT payload in both token creation functions
- [x] 6.6 Update all call sites for `create_token()` in `routers/auth.py`
- [x] 6.7 Reduce default `JWT_EXPIRY_HOURS` from 24 to 1
- [x] 6.8 Add test: user with `is_admin=1` column but viewer role resolves as non-admin
- [x] 6.9 Add test: role change via API persists correctly to database
- [x] 6.10 Add test: admin role passes all permission checks through RBAC (not shortcut)

## 7. Security Regression Tests

- [x] 7.1 Add `tests/security/test_auth.py` with brute-force lockout test
- [x] 7.2 Add test for default admin password change enforcement
- [x] 7.3 Add test for logout-refresh-token-revocation
- [x] 7.4 Add test for token revocation persistence across restarts
- [x] 7.5 Add test for audit log failure alerting

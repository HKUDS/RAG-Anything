# -*- coding: utf-8 -*-
"""
RAG-Anything Authentication Service — PostgreSQL-backed.

Layer: Service
Primary Responsibility: bcrypt password hashing, JWT token issuance/verification,
    account lockout protection.  User/role/audit/token storage is delegated to
    ``raganything.services.pg_auth_repo`` (PostgreSQL required).
"""

import os
import uuid
from datetime import datetime, timedelta
from typing import Optional

import jwt as pyjwt
from passlib.context import CryptContext

from raganything.permissions import DEFAULT_ROLE_NAME

# ── Password Hashing ───────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ═══════════════════════════════════════════════════════════════
# PostgreSQL Backend (required — no SQLite fallback)
# ═══════════════════════════════════════════════════════════════

from raganything.services.pg_auth_repo import (  # noqa: E402 — intentional late import
    # User / Role CRUD
    init_db,
    get_user_by_username,
    get_user_by_id,
    create_user,
    update_user,
    delete_user,
    list_users,
    get_user_role,
    get_role_by_name,
    list_roles,
    has_permission,
    user_is_admin,
    # Account protection
    check_account_locked,
    record_failed_login,
    reset_failed_logins,
    update_last_login_at,
    # Token blacklist
    pg_is_token_revoked,
    pg_revoke_token,
    pg_revoke_refresh_family,
    pg_register_refresh_family,
    pg_rotate_refresh_token,
    # Audit log
    pg_audit_log,
    pg_query_audit_logs,
    # Constants supplied by the process environment at startup
    SECRET_KEY as _PG_SECRET_KEY,
    REFRESH_SECRET_KEY as _PG_REFRESH_SECRET_KEY,
    JWT_EXPIRY_HOURS,
    REFRESH_EXPIRY_DAYS,
    ALGORITHM,
    SERVER_START_ID as _PG_SERVER_START_ID,
    DEFAULT_ADMIN_USERNAME as _PG_DEFAULT_ADMIN_USERNAME,
    DEFAULT_ADMIN_PASSWORD as _PG_DEFAULT_ADMIN_PASSWORD,
    production_configuration_errors,
    validate_production_configuration,
    public_registration_enabled,
    # Password hashing (delegated — pg_auth_repo also uses passlib/bcrypt)
    verify_password as _pg_verify_password,
)

# Mirror the repository's environment-derived constants so JWT sign/verify use
# the configured process values shared by every deployed worker.
SECRET_KEY = _PG_SECRET_KEY
REFRESH_SECRET_KEY = _PG_REFRESH_SECRET_KEY
SERVER_START_ID = _PG_SERVER_START_ID
DEFAULT_ADMIN_USERNAME = _PG_DEFAULT_ADMIN_USERNAME
DEFAULT_ADMIN_PASSWORD = _PG_DEFAULT_ADMIN_PASSWORD


def refresh_runtime_constants() -> None:
    """Synchronize JWT constants after PostgreSQL startup initialization."""
    from raganything.services import pg_auth_repo

    global SECRET_KEY, REFRESH_SECRET_KEY, SERVER_START_ID
    SECRET_KEY = pg_auth_repo.SECRET_KEY
    REFRESH_SECRET_KEY = pg_auth_repo.REFRESH_SECRET_KEY
    SERVER_START_ID = pg_auth_repo.SERVER_START_ID


# ── Token Blacklist (async wrappers around PG functions) ────

async def is_token_revoked(jti: str) -> bool:
    return await pg_is_token_revoked(jti)

async def revoke_token(jti: str, expires_at, family_id: str | None = None):
    await pg_revoke_token(jti, expires_at, family_id)

async def revoke_refresh_family(family_id: str):
    await pg_revoke_refresh_family(family_id)

async def register_refresh_family(family_id: str, jti: str, expires_at=None):
    await pg_register_refresh_family(family_id, jti, expires_at)


async def rotate_refresh_token(
    family_id: str, old_jti: str, new_jti: str, new_expires_at,
) -> bool:
    return await pg_rotate_refresh_token(
        family_id, old_jti, new_jti, new_expires_at,
    )


# ── Audit Log (async wrappers around PG functions) ──────────

async def audit_log(
    actor_id: int,
    action: str,
    target_user_id: int | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
):
    await pg_audit_log(actor_id, action, target_user_id, details, ip_address)

async def query_audit_logs(
    page: int = 1,
    page_size: int = 20,
    actor_id: int | None = None,
    action: str | None = None,
) -> dict:
    return await pg_query_audit_logs(page, page_size, actor_id, action)


# ═══════════════════════════════════════════════════════════════
# JWT Utilities (local — no DB access needed)
# ═══════════════════════════════════════════════════════════════

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_token(
    user_id: int,
    username: str,
    is_admin: bool,
    role: dict | None = None,
    session_generation: int = 0,
) -> str:
    """Issue a JWT access token. Authority (is_admin) is NOT embedded —
    it is derived server-side from the RBAC role on every request.
    Role information (name + permissions) is embedded for client-side display only."""
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role.get("name") if role else ("super_admin" if is_admin else DEFAULT_ROLE_NAME),
        "permissions": role.get("permissions") if role else [],
        "sid": SERVER_START_ID,
        "sg": int(session_generation),
        "jti": uuid.uuid4().hex,
        "type": "access",
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.utcnow(),
    }
    return pyjwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    """Verify and decode a JWT access token. Returns None if invalid or expired."""
    try:
        payload = pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("sid") != SERVER_START_ID:
            return None
        return payload
    except pyjwt.ExpiredSignatureError:
        return None
    except pyjwt.InvalidTokenError:
        return None


def create_refresh_token(
    user_id: int,
    username: str,
    is_admin: bool,
    role: dict | None = None,
    session_generation: int = 0,
    family_id: str | None = None,
) -> str:
    """Issue a JWT refresh token (7-day expiry). Authority is NOT embedded."""
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role.get("name") if role else ("super_admin" if is_admin else DEFAULT_ROLE_NAME),
        "permissions": role.get("permissions") if role else [],
        "type": "refresh",
        "sid": SERVER_START_ID,
        "sg": int(session_generation),
        "jti": uuid.uuid4().hex,
        "rfam": family_id or uuid.uuid4().hex,
        "exp": datetime.utcnow() + timedelta(days=REFRESH_EXPIRY_DAYS),
        "iat": datetime.utcnow(),
    }
    return pyjwt.encode(payload, REFRESH_SECRET_KEY, algorithm=ALGORITHM)


def decode_refresh_token(token: str) -> dict | None:
    """Verify and decode a JWT refresh token. Returns None if invalid."""
    try:
        payload = pyjwt.decode(token, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            return None
        if payload.get("sid") != SERVER_START_ID:
            return None
        return payload
    except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError):
        return None


# ── Helpers ────────────────────────────────────────────────

def _sanitize_user(user: dict | None) -> dict | None:
    """Remove password_hash from user dict for safe serialization."""
    if user is None:
        return None
    return {k: v for k, v in user.items() if k != "password_hash"}


def get_db_path():
    """Deprecated. Kept for backward-compat with tests. Always returns None."""
    return None

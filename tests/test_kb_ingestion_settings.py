import json
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException

from raganything.permissions import DEFAULT_ROLES, Permission
from raganything.routers import knowledge
from raganything.services import pg_kb_meta_repo


def test_five_role_matrix_keeps_students_read_only_and_other_roles_write_capable():
    for role_name, role in DEFAULT_ROLES.items():
        permissions = set(role["permissions"])
        assert Permission.KB_READ in permissions, role_name
        assert (Permission.KB_WRITE in permissions) is (role_name != "student")


@pytest.mark.asyncio
async def test_kb_ingestion_update_preserves_unrelated_extra_and_advances_revision(monkeypatch):
    state = {
        "extra": {
            "vision_embedding": {"profile_id": "vision-a"},
            "ingestion_defaults": {"parser": "docling"},
            "ingestion_defaults_revision": 4,
        }
    }

    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class Connection:
        def transaction(self):
            return Transaction()

        async def fetchrow(self, sql, name):
            assert "FOR UPDATE" in sql
            assert name == "demo"
            return {"extra": state["extra"]}

        async def execute(self, _sql, _name, extra_json):
            state["extra"] = json.loads(extra_json)
            return "UPDATE 1"

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Connection()

    monkeypatch.setattr(pg_kb_meta_repo, "_get_pool", lambda: Pool())
    result = await pg_kb_meta_repo.pg_update_kb_ingestion_defaults(
        "demo", {"chunk_size": 800}, 4,
    )

    assert result == ({"chunk_size": 800}, 5)
    assert state["extra"] == {
        "vision_embedding": {"profile_id": "vision-a"},
        "ingestion_defaults": {"chunk_size": 800},
        "ingestion_defaults_revision": 5,
    }


@pytest.mark.asyncio
async def test_kb_ingestion_update_rejects_stale_revision_without_write(monkeypatch):
    calls = []

    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class Connection:
        def transaction(self):
            return Transaction()

        async def fetchrow(self, _sql, _name):
            return {"extra": {"ingestion_defaults_revision": 2}}

        async def execute(self, *_args):
            calls.append("write")

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Connection()

    monkeypatch.setattr(pg_kb_meta_repo, "_get_pool", lambda: Pool())
    assert await pg_kb_meta_repo.pg_update_kb_ingestion_defaults("demo", {}, 1) is None
    assert calls == []


@pytest.mark.asyncio
async def test_ingestion_put_checks_kb_scope_and_returns_revisioned_state(monkeypatch):
    verified = []
    audited = []

    async def verify(kb, user):
        verified.append((kb, user["id"]))
        return kb

    async def platform():
        return {"settings": {"defaults": {}, "allowed": {}, "limits": {}, "state": {}}}

    async def update(kb, values, revision):
        assert (kb, values, revision) == ("demo", {"parser": "docling"}, 3)
        return values, 4

    async def state(kb, user_id):
        return {"kb": kb, "revision": 4, "stored": {"parser": "docling"}, "effective": {}, "sources": {}, "constraints": {}}

    async def audit(*args, **kwargs):
        audited.append((args, kwargs))

    monkeypatch.setattr(knowledge, "verify_kb_access", verify)
    monkeypatch.setattr(knowledge, "_kb_ingestion_state", state)
    monkeypatch.setattr(knowledge, "audit_log", audit)
    monkeypatch.setattr("raganything.services.user_settings.get_platform_settings", platform)
    monkeypatch.setattr(pg_kb_meta_repo, "pg_update_kb_ingestion_defaults", update)

    result = await knowledge.update_kb_ingestion_settings(
        "demo",
        knowledge.KBIngestionSettingsUpdate(expected_revision=3, values={"parser": "docling"}),
        user={"id": 8},
    )

    assert result["revision"] == 4
    assert verified == [("demo", 8)]
    assert audited[0][0][1] == "kb.ingestion_settings.updated"


@pytest.mark.asyncio
async def test_ingestion_put_rejects_invalid_values_and_revision_conflicts(monkeypatch):
    persisted = []

    async def verify(_kb, _user):
        return "demo"

    async def platform():
        return {"settings": {"defaults": {}, "allowed": {"parsers": ["mineru"]}, "limits": {}, "state": {}}}

    async def update(*args):
        persisted.append(args)
        return None

    monkeypatch.setattr(knowledge, "verify_kb_access", verify)
    monkeypatch.setattr("raganything.services.user_settings.get_platform_settings", platform)
    monkeypatch.setattr(pg_kb_meta_repo, "pg_update_kb_ingestion_defaults", update)

    with pytest.raises(HTTPException) as invalid:
        await knowledge.update_kb_ingestion_settings(
            "demo", knowledge.KBIngestionSettingsUpdate(expected_revision=0, values={"parser": "docling"}), user={"id": 8},
        )
    assert invalid.value.status_code == 422
    assert persisted == []

    with pytest.raises(HTTPException) as conflict:
        await knowledge.update_kb_ingestion_settings(
            "demo", knowledge.KBIngestionSettingsUpdate(expected_revision=0, values={"parser": "mineru"}), user={"id": 8},
        )
    assert conflict.value.status_code == 409

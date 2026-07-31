from contextlib import asynccontextmanager
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile


@asynccontextmanager
async def _acquire(value):
    yield value


class _Connection:
    def __init__(self, count):
        self.count = count
        self.calls = []

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        return self.count

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if "FROM kb_metadata" in sql:
            return {"extra": {}}
        return None

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return "UPDATE 1"


class _Pool:
    def __init__(self, count):
        self.connection = _Connection(count)

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


def _available_profile(profile_id="embedding-next", fingerprint="fingerprint-next", dim=1024):
    return SimpleNamespace(
        profile=SimpleNamespace(id=profile_id, embedding_dim=dim),
        fingerprint=fingerprint,
    )


@pytest.mark.asyncio
async def test_empty_kb_vision_profile_switches_immediately(monkeypatch):
    from raganything.routers import knowledge
    from raganything.services import vision_models

    metadata = {"demo": {"extra": {}}}
    saved = []
    events = []
    pool = _Pool(0)

    async def load_meta():
        return metadata

    async def save_meta(value):
        saved.append(value)

    async def audit(*args, **kwargs):
        events.append((args, kwargs))

    monkeypatch.setattr(knowledge, "load_kb_meta", load_meta)
    monkeypatch.setattr(knowledge, "save_kb_meta", save_meta)
    monkeypatch.setattr(vision_models, "_pg_pool", lambda: _resolved(pool))
    monkeypatch.setattr(vision_models, "require_available", lambda *_: _available_profile())
    monkeypatch.setattr(vision_models, "audit_vision_event", audit)

    result = await knowledge.update_kb_vision_settings(
        "demo", knowledge.VisionSettingsUpdate(profile_id="embedding-next"),
        _access="demo", current_user={"id": 7},
    )

    assert result["vision_embedding"]["profile_id"] == "embedding-next"
    assert result["vision_embedding"]["index_state"] == "idle"
    assert saved == []
    assert any("pg_advisory_xact_lock" in sql for sql, _ in pool.connection.calls)
    assert events


@pytest.mark.asyncio
@pytest.mark.parametrize("uploads_active,lease_active", [(True, False), (False, True)])
async def test_empty_profile_switch_is_blocked_by_upload_or_mutation_lease(
    monkeypatch, tmp_path, uploads_active, lease_active,
):
    from raganything.services import vision_models

    class Connection:
        def __init__(self):
            self.calls = []
            self.flags = iter([uploads_active, lease_active])

        @asynccontextmanager
        async def transaction(self):
            yield self

        async def execute(self, sql, *args):
            self.calls.append((sql, args))
            return "UPDATE 1"

        async def fetchrow(self, sql, *args):
            self.calls.append((sql, args))
            return {"extra": {}}

        async def fetchval(self, sql, *args):
            self.calls.append((sql, args))
            return next(self.flags)

    connection = Connection()
    pool = SimpleNamespace(acquire=lambda: _acquire(connection))
    monkeypatch.setattr(vision_models, "_pg_pool", lambda: _resolved(pool))

    with pytest.raises(RuntimeError, match="vision_mutation_in_progress"):
        await vision_models.activate_empty_vision_profile(
            kb="demo", workspace=str(tmp_path), target=_available_profile(),
        )

    sql = [statement for statement, _ in connection.calls]
    assert sql[0].startswith("SELECT pg_advisory_xact_lock")
    assert not any(statement.startswith("UPDATE kb_metadata") for statement in sql)


@pytest.mark.asyncio
async def test_populated_kb_vision_profile_requires_explicit_reindex(monkeypatch):
    from raganything.routers import knowledge
    from raganything.services import vision_models

    pool = _Pool(3)

    async def load_meta():
        return {"demo": {"extra": {"vision_embedding": {
            "profile_id": "embedding-old", "profile_fingerprint": "fingerprint-old"
        }}}}

    monkeypatch.setattr(knowledge, "load_kb_meta", load_meta)
    monkeypatch.setattr(vision_models, "_pg_pool", lambda: _resolved(pool))
    monkeypatch.setattr(vision_models, "require_available", lambda *_: _available_profile())

    with pytest.raises(HTTPException) as raised:
        await knowledge.update_kb_vision_settings(
            "demo", knowledge.VisionSettingsUpdate(profile_id="embedding-next"),
            _access="demo", current_user={"id": 7},
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "reindex_required"
    assert "profile_id=$2" in pool.connection.calls[0][0]


@pytest.mark.asyncio
async def test_populated_kb_vision_profile_queues_confirmed_reindex(monkeypatch):
    from raganything.routers import knowledge
    from raganything.services import vision_models

    pool = _Pool(2)
    queued = []

    async def load_meta():
        return {"demo": {"extra": {"vision_embedding": {
            "profile_id": "embedding-old", "profile_fingerprint": "fingerprint-old"
        }}}}

    async def create_job(**kwargs):
        queued.append(kwargs)

    async def audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge, "load_kb_meta", load_meta)
    monkeypatch.setattr(vision_models, "_pg_pool", lambda: _resolved(pool))
    monkeypatch.setattr(vision_models, "require_available", lambda *_: _available_profile())
    monkeypatch.setattr(vision_models, "get_entry", lambda *_: _available_profile("embedding-old", "fingerprint-old", 512))
    monkeypatch.setattr(vision_models, "create_reindex_job", create_job)
    monkeypatch.setattr(vision_models, "schedule_reindex_job", lambda task_id: queued.append({"scheduled": task_id}))
    monkeypatch.setattr(vision_models, "audit_vision_event", audit)

    response = await knowledge.update_kb_vision_settings(
        "demo", knowledge.VisionSettingsUpdate(profile_id="embedding-next", reindex=True),
        _access="demo", current_user={"id": 7},
    )

    assert response.status_code == 202
    assert queued[0]["source"].profile.id == "embedding-old"
    assert queued[0]["target"].profile.id == "embedding-next"
    assert queued[0]["total"] == 2


@pytest.mark.asyncio
async def test_nano_active_partition_requires_reindex_even_when_pg_is_empty(monkeypatch):
    from raganything.routers import knowledge
    from raganything.services import vision_models

    async def load_meta():
        return {"demo": {"extra": {"vision_embedding": {
            "profile_id": "embedding-old", "profile_fingerprint": "fingerprint-old"
        }}}}

    monkeypatch.setattr(knowledge, "load_kb_meta", load_meta)
    monkeypatch.setattr(vision_models, "_pg_pool", lambda: _resolved(_Pool(0)))
    monkeypatch.setattr(vision_models, "require_available", lambda *_: _available_profile())
    monkeypatch.setattr(vision_models, "_load_nano_reindex_rows", lambda *_: ([{"image_hash": "x"}], None))

    with pytest.raises(HTTPException) as raised:
        await knowledge.update_kb_vision_settings(
            "demo", knowledge.VisionSettingsUpdate(profile_id="embedding-next"),
            _access="demo", current_user={"id": 7},
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "reindex_required"


@pytest.mark.asyncio
async def test_kb_owner_can_change_vision_profile_without_role_permission(monkeypatch):
    from raganything.routers import knowledge

    async def access(kb, _user):
        return kb

    async def metadata():
        return {"demo": {"owner_id": 7}}

    async def forbidden_permission(*_args):
        raise AssertionError("owner path must not require kb:write")

    monkeypatch.setattr(knowledge, "verify_kb_access", access)
    monkeypatch.setattr(knowledge, "load_kb_meta", metadata)
    monkeypatch.setattr(knowledge, "_auth_has_permission", forbidden_permission)

    assert await knowledge._verify_kb_vision_write_access("demo", {"id": 7}) == "demo"


@pytest.mark.asyncio
async def test_non_owner_without_kb_write_cannot_change_vision_profile(monkeypatch):
    from raganything.routers import knowledge

    async def access(kb, _user):
        return kb

    async def metadata():
        return {"demo": {"owner_id": 9}}

    async def no_permission(*_args):
        return False

    monkeypatch.setattr(knowledge, "verify_kb_access", access)
    monkeypatch.setattr(knowledge, "load_kb_meta", metadata)
    monkeypatch.setattr(knowledge, "_auth_has_permission", no_permission)

    with pytest.raises(HTTPException) as raised:
        await knowledge._verify_kb_vision_write_access("demo", {"id": 7})
    assert raised.value.status_code == 403


@pytest.mark.asyncio
async def test_image_search_uses_kb_profile_not_legacy_environment_gate(monkeypatch):
    from raganything.routers import knowledge

    class Repo:
        async def reload(self):
            return None

        async def query(self, _vector, top_k):
            assert top_k == 10
            return []

        def count(self):
            return 0

    class Vision:
        async def embed_image(self, _path):
            return [0.1, 0.2]

    instance = SimpleNamespace(
        lightrag=SimpleNamespace(image_vision_repo=Repo()),
        vision_embed_func=Vision(),
    )

    async def metadata():
        return {"demo": {"extra": {"vision_embedding": {
            "profile_id": "embedding-active", "profile_fingerprint": "fp"
        }}}}

    async def empty_statuses(_kb):
        return {}

    monkeypatch.setenv("VISION_SEARCH_ENABLED", "false")
    monkeypatch.setattr(knowledge, "load_kb_meta", metadata)
    monkeypatch.setattr(knowledge, "get_kb", lambda _kb: _resolved(instance))
    monkeypatch.setattr(knowledge, "_load_doc_status_json", empty_statuses)

    result = await knowledge.image_search(
        request=None,
        image=UploadFile(filename="query.jpg", file=BytesIO(b"image")),
        top_k=10,
        kb="demo",
        current_user={"id": 7},
    )

    assert result["count"] == 0


class _JobConnection:
    def __init__(self, job, *, source_rows=None, fail_statement=None):
        self.job = job
        self.source_rows = source_rows or []
        self.fail_statement = fail_statement
        self.executed = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def fetchrow(self, sql, *args):
        self.executed.append((sql, args))
        if "UPDATE vision_reindex_jobs SET state='running'" in sql:
            return self.job
        raise AssertionError(f"Unexpected fetchrow: {sql}")

    async def fetch(self, sql, *args):
        if "FROM image_vision_vectors" in sql:
            return self.source_rows
        raise AssertionError(f"Unexpected fetch: {sql}")

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        if self.fail_statement and self.fail_statement in sql:
            return "UPDATE 0"
        return "UPDATE 1"


class _JobPool:
    def __init__(self, job, *, source_rows=None, fail_statement=None):
        self.connection = _JobConnection(
            job, source_rows=source_rows, fail_statement=fail_statement
        )

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


class _GcConnection:
    def __init__(self, *, reverse=False, owned=True, active=True):
        self.reverse = reverse
        self.owned = owned
        self.active = active
        self.executed = []
        self.job = {
            "id": "00000000-0000-0000-0000-000000000001",
            "kb": "demo",
            "workspace": "C:/tmp/demo",
            "obsolete_profile_id": "embedding-old",
            "obsolete_fingerprint": "fingerprint-old",
            "required_active_profile_id": "embedding-next",
            "required_active_fingerprint": "fingerprint-next",
            "generation": 1,
            "state": "running",
            "lease_owner": None,
        }

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def fetchrow(self, sql, *args):
        self.executed.append((sql, args))
        if sql.startswith("UPDATE vision_index_gc_jobs SET state='running'"):
            self.job["lease_owner"] = args[1]
            return dict(self.job)
        if sql.startswith("SELECT * FROM vision_index_gc_jobs"):
            if not self.owned:
                return {**self.job, "lease_owner": "another-owner"}
            return dict(self.job)
        if sql.startswith("SELECT extra FROM kb_metadata"):
            if self.active:
                return {"extra": {"vision_embedding": {
                    "profile_id": "embedding-next",
                    "profile_fingerprint": "fingerprint-next",
                }}}
            return {"extra": {"vision_embedding": {
                "profile_id": "embedding-old",
                "profile_fingerprint": "fingerprint-old",
            }}}
        raise AssertionError(f"Unexpected fetchrow: {sql}")

    async def fetchval(self, sql, *args):
        self.executed.append((sql, args))
        if sql.startswith("SELECT kb FROM vision_index_gc_jobs"):
            return self.job["kb"]
        if "FROM vision_reindex_jobs" in sql:
            return self.reverse
        raise AssertionError(f"Unexpected fetchval: {sql}")

    async def fetch(self, sql, *args):
        self.executed.append((sql, args))
        if "FROM vision_index_gc_jobs WHERE state='queued'" in sql:
            return [{"id": self.job["id"]}]
        raise AssertionError(f"Unexpected fetch: {sql}")

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "UPDATE 1"


class _GcPool:
    def __init__(self, **kwargs):
        self.connection = _GcConnection(**kwargs)

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


def _reindex_job():
    return {
        "kb": "demo", "actor_id": 7, "target_profile_id": "embedding-next",
        "target_fingerprint": "fingerprint-next", "source_profile_id": "embedding-old",
        "source_fingerprint": "fingerprint-old", "source_embedding_dim": 512,
        "target_embedding_dim": 512, "completed": 0, "total": 1, "generation": 1,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("target_dim", [512, 1024])
async def test_reindex_success_activates_and_persists_old_partition_gc(monkeypatch, tmp_path, target_dim):
    from raganything.services import kb_service, vision_models

    pool = _JobPool(_reindex_job())
    events = []
    scheduled_gc = []

    class Repo:
        def __init__(self, *_args, **_kwargs):
            pass

        async def initialize(self, _dim):
            return None

        async def flush(self):
            return None

    async def audit(*args, **kwargs):
        events.append((args, kwargs))

    monkeypatch.setattr(vision_models, "_pg_pool", lambda: _resolved(pool))
    monkeypatch.setattr(vision_models, "require_available", lambda *_: _available_profile(dim=target_dim))
    monkeypatch.setattr(vision_models, "build_embedding_provider", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("raganything.embedding.image_vector_repo.ImageVectorRepository", Repo)
    monkeypatch.setattr(kb_service, "kb_dir", lambda _kb: str(tmp_path))
    monkeypatch.setattr(kb_service, "kb_instances", {})
    monkeypatch.setattr(vision_models, "audit_vision_event", audit)
    monkeypatch.setattr(vision_models, "schedule_vision_gc_job", scheduled_gc.append)

    await vision_models.run_reindex_job("job-success")

    sql = [item[0] for item in pool.connection.executed]
    activation = next(i for i, statement in enumerate(sql) if "SET extra=jsonb_set(extra,'{vision_embedding}'" in statement)
    durable_gc = next(i for i, statement in enumerate(sql) if statement.startswith("INSERT INTO vision_index_gc_jobs"))
    assert durable_gc > activation
    assert not any(statement.startswith("DELETE FROM image_vision_vectors") for statement in sql)
    assert scheduled_gc == [pool.connection.executed[durable_gc][1][0]]
    assert f'"embedding_dim": {target_dim}' in pool.connection.executed[activation][1][1]
    assert events[-1][0][1] == "vision.kb_reindex.succeeded"


@pytest.mark.asyncio
async def test_reindex_failure_cleans_target_and_preserves_active_metadata(monkeypatch, tmp_path):
    from raganything.services import kb_service, vision_models

    pool = _JobPool(_reindex_job())
    events = []

    async def audit(*args, **kwargs):
        events.append((args, kwargs))

    monkeypatch.setattr(vision_models, "_pg_pool", lambda: _resolved(pool))
    monkeypatch.setattr(vision_models, "require_available", lambda *_: _available_profile())
    monkeypatch.setattr(vision_models, "build_embedding_provider", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("provider down")))
    monkeypatch.setattr(kb_service, "kb_dir", lambda _kb: str(tmp_path))
    monkeypatch.setattr(vision_models, "audit_vision_event", audit)

    await vision_models.run_reindex_job("job-failure")

    sql = [item[0] for item in pool.connection.executed]
    assert any(statement.startswith("DELETE FROM image_vision_vectors") for statement in sql)
    assert any("'{vision_embedding,index_state}'" in statement for statement in sql)
    assert events[-1][0][1] == "vision.kb_reindex.failed"


@pytest.mark.asyncio
async def test_reindex_lost_owner_cannot_activate_or_clean_target(monkeypatch, tmp_path):
    from raganything.services import kb_service, vision_models

    pool = _JobPool(_reindex_job(), fail_statement="SET state='succeeded'")
    events = []

    class Repo:
        def __init__(self, *_args, **_kwargs):
            pass

        async def initialize(self, _dim):
            return None

        async def flush(self):
            return None

    async def audit(*args, **kwargs):
        events.append((args, kwargs))

    monkeypatch.setattr(vision_models, "_pg_pool", lambda: _resolved(pool))
    monkeypatch.setattr(vision_models, "require_available", lambda *_: _available_profile())
    monkeypatch.setattr(vision_models, "build_embedding_provider", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("raganything.embedding.image_vector_repo.ImageVectorRepository", Repo)
    monkeypatch.setattr(kb_service, "kb_dir", lambda _kb: str(tmp_path))
    monkeypatch.setattr(kb_service, "kb_instances", {})
    monkeypatch.setattr(vision_models, "audit_vision_event", audit)

    await vision_models.run_reindex_job("job-lost-owner")

    sql = [item[0] for item in pool.connection.executed]
    assert any("generation=generation+1" in statement for statement in sql)
    assert not any("SET extra=jsonb_set(extra,'{vision_embedding}'" in statement for statement in sql)
    assert not any(statement.startswith("DELETE FROM image_vision_vectors") for statement in sql)
    assert events == []


@pytest.mark.asyncio
async def test_vision_gc_defers_when_reverse_reindex_targets_obsolete_partition(monkeypatch):
    from raganything.services import vision_models

    pool = _GcPool(reverse=True)
    removed = []
    monkeypatch.setattr(vision_models, "_pg_pool", lambda: _resolved(pool))
    monkeypatch.setattr(vision_models, "_remove_nano_partition", lambda *args: removed.append(args))

    await vision_models.run_vision_gc_job(pool.connection.job["id"])

    sql = [statement for statement, _ in pool.connection.executed]
    assert not any(statement.startswith("DELETE FROM image_vision_vectors") for statement in sql)
    assert any("SET state='queued'" in statement and "error_code=$4" in statement for statement in sql)
    assert removed == []


@pytest.mark.asyncio
async def test_vision_gc_lost_owner_cannot_delete_partition(monkeypatch):
    from raganything.services import vision_models

    pool = _GcPool(owned=False)
    removed = []
    monkeypatch.setattr(vision_models, "_pg_pool", lambda: _resolved(pool))
    monkeypatch.setattr(vision_models, "_remove_nano_partition", lambda *args: removed.append(args))

    await vision_models.run_vision_gc_job(pool.connection.job["id"])

    sql = [statement for statement, _ in pool.connection.executed]
    assert not any(statement.startswith("DELETE FROM image_vision_vectors") for statement in sql)
    assert removed == []


@pytest.mark.asyncio
async def test_vision_gc_nano_failure_is_requeued_and_retry_succeeds(monkeypatch):
    from raganything.services import vision_models

    pool = _GcPool()
    attempts = []

    def remove(*args):
        attempts.append(args)
        if len(attempts) == 1:
            raise OSError("sharing violation")

    monkeypatch.setattr(vision_models, "_pg_pool", lambda: _resolved(pool))
    monkeypatch.setattr(vision_models, "_remove_nano_partition", remove)

    await vision_models.run_vision_gc_job(pool.connection.job["id"])
    await vision_models.run_vision_gc_job(pool.connection.job["id"])

    sql = [statement for statement, _ in pool.connection.executed]
    assert any("SET state='queued'" in statement and "error_code=$4" in statement for statement in sql)
    assert any("SET state='succeeded'" in statement for statement in sql)
    assert len(attempts) == 2


@pytest.mark.asyncio
async def test_vision_gc_restart_requeues_stale_claims_and_schedules_pending(monkeypatch):
    from raganything.services import vision_models

    pool = _GcPool()
    scheduled = []
    monkeypatch.setattr(vision_models, "_pg_pool", lambda: _resolved(pool))
    monkeypatch.setattr(vision_models, "schedule_vision_gc_job", scheduled.append)

    count = await vision_models.resume_vision_gc_jobs()

    sql = [statement for statement, _ in pool.connection.executed]
    assert any("error_code='stale_lease'" in statement for statement in sql)
    assert count == 1
    assert scheduled == [pool.connection.job["id"]]


@pytest.mark.asyncio
async def test_vision_gc_is_idempotent_after_job_is_no_longer_claimable(monkeypatch):
    from raganything.services import vision_models

    pool = _GcPool()
    removed = []
    original_fetchrow = pool.connection.fetchrow

    async def no_claim(sql, *args):
        if sql.startswith("UPDATE vision_index_gc_jobs SET state='running'"):
            return None
        return await original_fetchrow(sql, *args)

    monkeypatch.setattr(pool.connection, "fetchrow", no_claim)
    monkeypatch.setattr(vision_models, "_pg_pool", lambda: _resolved(pool))
    monkeypatch.setattr(vision_models, "_remove_nano_partition", lambda *args: removed.append(args))

    await vision_models.run_vision_gc_job(pool.connection.job["id"])

    assert removed == []


async def _resolved(value):
    return value

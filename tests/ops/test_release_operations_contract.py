from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_alerts_have_required_categories_and_runbook_links():
    content = (ROOT / "deploy" / "prometheus" / "release-operations-alerts.yml").read_text(encoding="utf-8")
    for category in ("ApplicationUnavailable", "PostgresUnavailable", "RedisUnavailable", "DiskLow", "BackupStale"):
        assert category in content
    assert content.count("for:") >= 5
    assert content.count("runbook_url:") >= 5


def test_handoff_records_shared_entrypoint_integration():
    content = (ROOT / "docs" / "ops" / "release-operations-handoff.md").read_text(encoding="utf-8")
    assert "/api/live" in content and "/api/ready" in content
    assert "coordinator" in content
    assert "PGPASSFILE" in content


def test_integration_gaps_name_upload_sse_and_certificate_owners():
    content = (ROOT / "deploy" / "prometheus" / "release-operations-integration-gaps.md").read_text(encoding="utf-8")
    for term in ("rag_upload_queue_oldest_seconds", "rag_sse_stream_events_total", "probe_ssl_earliest_cert_expiry"):
        assert term in content
    wrapper = (ROOT / "deploy" / "release-backup-offsite.example.sh").read_text(encoding="utf-8")
    assert "BACKUP_ENCRYPT_COMMAND" in wrapper and "BACKUP_UPLOAD_COMMAND" in wrapper


def test_compose_runs_migrations_only_after_explicit_backup_acknowledgement():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "migrate:" in compose
    assert "service_completed_successfully" in compose
    assert "MIGRATION_BACKUP_ACKNOWLEDGED" in compose
    assert "POSTGRES_PASSWORD:-raganything" not in compose
    assert "POSTGRES_USER:-raganything" not in compose
    assert "POSTGRES_DATABASE:-raganything" not in compose
    assert "DATABASE_URL:?DATABASE_URL must be set" in compose
    assert "RAGANYTHING_ENV:?RAGANYTHING_ENV must be set" in compose
    assert "RAG_STORAGE_HOST_PATH" in compose
    assert '"443:443"' not in compose
    nginx = (ROOT / "nginx.conf").read_text(encoding="utf-8")
    assert "Strict-Transport-Security" not in nginx

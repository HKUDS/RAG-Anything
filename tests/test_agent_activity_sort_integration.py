import uuid
from datetime import datetime, timezone

import pytest

from raganything.services.pg_agent_repo import (
    pg_create_agent,
    pg_create_conversation,
    pg_delete_agent,
    pg_list_agents,
)


def _pg_ready():
    try:
        from raganything.services.pg_state_repo import get_pg_pool

        get_pg_pool()
        return True
    except (RuntimeError, ImportError):
        return False


pytestmark = pytest.mark.skipif(not _pg_ready(), reason="PostgreSQL connection pool is not initialized")


@pytest.mark.asyncio
async def test_agent_activity_uses_owner_scope_for_users_and_all_scope_for_admins():
    from raganything.services.pg_state_repo import get_pg_pool

    suffix = uuid.uuid4().hex[:8]
    active_agent = await pg_create_agent(
        {"name": f"activity-{suffix}", "kb_name": "default"},
        owner_id=42,
        owner_username="alice",
    )
    idle_agent = await pg_create_agent(
        {"name": f"idle-{suffix}", "kb_name": "default"},
        owner_id=42,
        owner_username="alice",
    )

    try:
        alice_thread = await pg_create_conversation(active_agent["id"], owner_id=42)
        bob_thread = await pg_create_conversation(active_agent["id"], owner_id=99)
        pool = get_pg_pool()
        await pool.execute(
            "UPDATE agent_conversations SET updated_at = $1 WHERE id = $2",
            datetime(2026, 7, 10, tzinfo=timezone.utc),
            alice_thread["id"],
        )
        await pool.execute(
            "UPDATE agent_conversations SET updated_at = $1 WHERE id = $2",
            datetime(2026, 7, 11, tzinfo=timezone.utc),
            bob_thread["id"],
        )

        user_agents = {agent["id"]: agent for agent in await pg_list_agents(user_id=42, is_admin=False)}
        admin_agents = {agent["id"]: agent for agent in await pg_list_agents(user_id=1, is_admin=True)}

        assert user_agents[active_agent["id"]]["conversation_count"] == 1
        assert user_agents[active_agent["id"]]["last_conversation_at"].startswith("2026-07-10T00:00:00")
        assert admin_agents[active_agent["id"]]["conversation_count"] == 2
        assert admin_agents[active_agent["id"]]["last_conversation_at"].startswith("2026-07-11T00:00:00")
        assert user_agents[idle_agent["id"]]["conversation_count"] == 0
        assert user_agents[idle_agent["id"]]["last_conversation_at"] is None
    finally:
        await pg_delete_agent(active_agent["id"])
        await pg_delete_agent(idle_agent["id"])

# -*- coding: utf-8 -*-
"""
RAG-Anything Agent Manager Service.

Layer: Service
Primary Responsibility: Agent CRUD, conversation thread management.
Data Storage: PostgreSQL via pg_agent_repo (sole backend).

Migrated from JSON file persistence to PG-backed storage.
All public methods delegate to pg_agent_repo functions.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════

class AgentConfig(BaseModel):
    """Agent configuration model."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "新智能体"
    icon: str = "🤖"
    description: str = ""
    welcome_message: str = "你好！我是你的智能助手，有什么可以帮你的？"

    kb_name: str = "default"
    llm_model: str = "qwen-plus"
    temperature: float = 0.0
    max_response_tokens: int = 4096

    query_mode: str = "hybrid"
    agent_mode: str = "none"
    retrieval_top_k: int = 40
    chunk_top_k: int = 20
    enable_rerank: bool = False
    include_references: bool = True

    system_prompt: str = ""
    use_default_prompt: bool = True

    owner_id: int = 0
    owner_username: str = ""

    template_id: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ConversationThread(BaseModel):
    """Conversation thread model."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = "新对话"
    owner_id: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    messages: list[dict] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# Agent Manager — PG-backed (sole backend)
# ═══════════════════════════════════════════════════════════

class AgentManager:
    """Agent manager: CRUD + persistence via PostgreSQL.

    All storage is delegated to pg_agent_repo functions.
    No JSON file fallback — PG is the sole backend.
    """

    def __init__(self, data_dir: str = "."):
        # data_dir is kept for backward compatibility but no longer used for storage
        self.data_dir = data_dir
        self._pg_available: bool | None = None

    @property
    def pg_available(self) -> bool:
        """Lazy-check PG availability (cached after first check)."""
        if self._pg_available is None:
            self._pg_available = _pg_agent_ready()
        return self._pg_available

    def _run(self, coro):
        """Run an async coroutine, bridging sync→async for backward compat."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        # Already in an async context — caller should use async methods directly.
        # For sync callers in a running loop, we raise a clear error.
        raise RuntimeError(
            "AgentManager sync methods cannot be called from within a running event loop. "
            "Use the async PG functions from pg_agent_repo directly."
        )

    # ── Agent CRUD ───────────────────────────────────────

    def list_agents(self, user_id: int = None, is_admin: bool = False) -> list[AgentConfig]:
        """List agents with user isolation (admin sees all)."""
        from raganything.services.pg_agent_repo import pg_list_agents
        rows = self._run(pg_list_agents(user_id=user_id, is_admin=is_admin))
        return [AgentConfig(**r) for r in rows]

    def get_agent(self, agent_id: str) -> AgentConfig | None:
        """Get a single agent by ID."""
        from raganything.services.pg_agent_repo import pg_get_agent
        row = self._run(pg_get_agent(agent_id))
        return AgentConfig(**row) if row else None

    def create_agent(self, config: AgentConfig | dict, owner_id: int = 0,
                     owner_username: str = "") -> AgentConfig:
        """Create an agent (injects ownership)."""
        from raganything.services.pg_agent_repo import pg_create_agent
        if isinstance(config, AgentConfig):
            config = config.model_dump()
        elif isinstance(config, dict):
            config = dict(config)
        row = self._run(pg_create_agent(config, owner_id=owner_id, owner_username=owner_username))
        return AgentConfig(**row)

    def update_agent(self, agent_id: str, updates: dict) -> AgentConfig | None:
        """Update agent configuration (partial update)."""
        from raganything.services.pg_agent_repo import pg_update_agent
        row = self._run(pg_update_agent(agent_id, updates))
        return AgentConfig(**row) if row else None

    def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent and all its conversations (CASCADE)."""
        from raganything.services.pg_agent_repo import pg_delete_agent
        return self._run(pg_delete_agent(agent_id))

    # ── Conversation Thread Management ────────────────────

    def list_conversations(self, agent_id: str, user_id: int = None,
                           is_admin: bool = False) -> list[ConversationThread]:
        """List conversation threads for an agent (user-isolated)."""
        from raganything.services.pg_agent_repo import pg_list_conversations
        rows = self._run(pg_list_conversations(agent_id, user_id=user_id, is_admin=is_admin))
        return [ConversationThread(**r) for r in rows]

    def get_conversation(self, agent_id: str, thread_id: str) -> ConversationThread | None:
        """Get a single conversation thread with messages."""
        from raganything.services.pg_agent_repo import pg_get_conversation
        row = self._run(pg_get_conversation(agent_id, thread_id))
        return ConversationThread(**row) if row else None

    def create_conversation(self, agent_id: str, title: str = "新对话",
                            owner_id: int = 0) -> ConversationThread:
        """Create a new conversation thread (injects ownership)."""
        from raganything.services.pg_agent_repo import pg_create_conversation
        row = self._run(pg_create_conversation(agent_id, title=title, owner_id=owner_id))
        return ConversationThread(**row)

    def add_message(self, agent_id: str, thread_id: str, message: dict) -> bool:
        """Add a message to a conversation thread."""
        from raganything.services.pg_agent_repo import pg_add_message
        return self._run(pg_add_message(agent_id, thread_id, message))

    def update_conversation(self, agent_id: str, thread_id: str,
                            updates: dict) -> ConversationThread | None:
        """Update a conversation thread (rename, etc.)."""
        from raganything.services.pg_agent_repo import pg_update_conversation
        row = self._run(pg_update_conversation(agent_id, thread_id, updates))
        return ConversationThread(**row) if row else None

    def delete_conversation(self, agent_id: str, thread_id: str) -> bool:
        """Delete a conversation thread."""
        from raganything.services.pg_agent_repo import pg_delete_conversation
        return self._run(pg_delete_conversation(agent_id, thread_id))

    # ── Migration ────────────────────────────────────────

    def ensure_default_agent(self, llm_model: str = "qwen-plus",
                              query_history: list[dict] = None):
        """Ensure a default agent exists, migrate legacy query history."""
        from raganything.services.pg_agent_repo import pg_ensure_default_agent
        agent_row, thread_row = self._run(
            pg_ensure_default_agent(llm_model=llm_model, query_history=query_history)
        )
        if agent_row is None:
            return None, None
        agent = AgentConfig(**agent_row)
        thread = ConversationThread(**thread_row) if thread_row else None
        return agent, thread

    def migrate_agents(self) -> int:
        """Migrate owner_id=0 agents and conversations to admin (user_id=1)."""
        from raganything.services.pg_agent_repo import pg_migrate_agents
        return self._run(pg_migrate_agents())


# ── Global Singleton ───────────────────────────────────────

agent_manager: AgentManager | None = None


def init_agent_manager(data_dir: str = ".") -> AgentManager:
    """Initialize the global agent manager singleton."""
    global agent_manager
    agent_manager = AgentManager(data_dir)
    return agent_manager


def get_agent_manager() -> AgentManager:
    """Get the global agent manager singleton."""
    if agent_manager is None:
        return init_agent_manager()
    return agent_manager


def _pg_agent_ready() -> bool:
    """Check if PG agent backend is available."""
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        get_pg_pool()
        return True
    except (RuntimeError, ImportError):
        return False

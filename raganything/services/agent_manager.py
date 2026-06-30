# -*- coding: utf-8 -*-
"""
RAG-Anything Agent Manager Service.

Layer: Service
Primary Responsibility: Agent CRUD, conversation thread management,
    persistence to disk (agent_meta.json, agent_conversations/).
Key Dependencies: pydantic, stdlib (json, uuid, shutil)

Migrated from root-level agent_manager.py. All original class/function signatures preserved.
"""

from __future__ import annotations

import json
import uuid
import shutil
from datetime import datetime
from pathlib import Path
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
# Agent Manager
# ═══════════════════════════════════════════════════════════

class AgentManager:
    """Agent manager: CRUD + persistence."""

    def __init__(self, data_dir: str = "."):
        self.data_dir = Path(data_dir)
        self.meta_file = self.data_dir / "agent_meta.json"
        self.conversations_dir = self.data_dir / "agent_conversations"

        self.agents: dict[str, AgentConfig] = {}
        self.conversations: dict[str, dict[str, ConversationThread]] = {}

        self._load()

    # ── Persistence ──────────────────────────────────────

    def _load(self):
        """Load agents and conversations from disk."""
        if self.meta_file.exists():
            try:
                data = json.loads(self.meta_file.read_text(encoding="utf-8"))
                for item in data.get("agents", []):
                    agent = AgentConfig(**item)
                    self.agents[agent.id] = agent
            except Exception as e:
                print(f"[AgentManager] 加载智能体失败: {e}，备份损坏文件")
                try:
                    import shutil as _shutil
                    _shutil.copy(self.meta_file, str(self.meta_file) + ".corrupted_backup")
                except Exception:
                    pass

        if self.conversations_dir.exists():
            for agent_dir in self.conversations_dir.iterdir():
                if agent_dir.is_dir():
                    agent_id = agent_dir.name
                    self.conversations[agent_id] = {}
                    for conv_file in agent_dir.glob("*.json"):
                        try:
                            data = json.loads(conv_file.read_text(encoding="utf-8"))
                            thread = ConversationThread(**data)
                            self.conversations[agent_id][thread.id] = thread
                        except Exception as e:
                            print(f"[AgentManager] 加载对话失败 {conv_file}: {e}")

    def _save_agents(self):
        """Persist agent metadata (atomic write)."""
        data = {
            "agents": [agent.model_dump() for agent in self.agents.values()],
            "updated_at": datetime.now().isoformat(),
        }
        tmp = self.meta_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.meta_file)

    def _save_conversation(self, agent_id: str, thread: ConversationThread):
        """Persist a single conversation thread (atomic write)."""
        conv_dir = self.conversations_dir / agent_id
        conv_dir.mkdir(parents=True, exist_ok=True)
        conv_file = conv_dir / f"{thread.id}.json"
        tmp = conv_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(thread.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(conv_file)

    # ── Agent CRUD ───────────────────────────────────────

    def list_agents(self, user_id: int = None, is_admin: bool = False) -> list[AgentConfig]:
        """List agents with user isolation (admin sees all)."""
        agents = self.agents.values()
        if not is_admin and user_id is not None:
            agents = [a for a in agents if a.owner_id == 0 or a.owner_id == user_id]
        return sorted(agents, key=lambda a: a.updated_at, reverse=True)

    def get_agent(self, agent_id: str) -> AgentConfig | None:
        """Get a single agent by ID."""
        return self.agents.get(agent_id)

    def create_agent(self, config: AgentConfig | dict, owner_id: int = 0,
                     owner_username: str = "") -> AgentConfig:
        """Create an agent (injects ownership)."""
        if isinstance(config, dict):
            config = AgentConfig(**config)
        if not config.id:
            config.id = str(uuid.uuid4())[:8]
        config.owner_id = owner_id
        config.owner_username = owner_username
        config.created_at = config.created_at or datetime.now().isoformat()
        config.updated_at = config.created_at
        self.agents[config.id] = config
        self._save_agents()
        return config

    def update_agent(self, agent_id: str, updates: dict) -> AgentConfig | None:
        """Update agent configuration (partial update)."""
        agent = self.agents.get(agent_id)
        if not agent:
            return None
        for key, value in updates.items():
            if hasattr(agent, key) and value is not None:
                setattr(agent, key, value)
        agent.updated_at = datetime.now().isoformat()
        self.agents[agent_id] = agent
        self._save_agents()
        return agent

    def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent and all its conversations."""
        if agent_id not in self.agents:
            return False
        del self.agents[agent_id]
        self._save_agents()

        if agent_id in self.conversations:
            conv_dir = self.conversations_dir / agent_id
            if conv_dir.exists():
                shutil.rmtree(conv_dir, ignore_errors=True)
            del self.conversations[agent_id]

        return True

    # ── Conversation Thread Management ────────────────────

    def list_conversations(self, agent_id: str, user_id: int = None,
                           is_admin: bool = False) -> list[ConversationThread]:
        """List conversation threads for an agent (user-isolated)."""
        threads = self.conversations.get(agent_id, {})
        result = threads.values()
        if not is_admin and user_id is not None:
            result = [t for t in result if t.owner_id == 0 or t.owner_id == user_id]
        return sorted(result, key=lambda t: t.updated_at, reverse=True)

    def get_conversation(self, agent_id: str, thread_id: str) -> ConversationThread | None:
        """Get a single conversation thread."""
        return self.conversations.get(agent_id, {}).get(thread_id)

    def create_conversation(self, agent_id: str, title: str = "新对话",
                            owner_id: int = 0) -> ConversationThread:
        """Create a new conversation thread (injects ownership)."""
        thread = ConversationThread(
            id=str(uuid.uuid4())[:8],
            title=title,
            owner_id=owner_id,
        )
        if agent_id not in self.conversations:
            self.conversations[agent_id] = {}
        self.conversations[agent_id][thread.id] = thread
        self._save_conversation(agent_id, thread)
        return thread

    def add_message(self, agent_id: str, thread_id: str, message: dict) -> bool:
        """Add a message to a conversation thread."""
        thread = self.get_conversation(agent_id, thread_id)
        if not thread:
            return False
        thread.messages.append(message)
        thread.updated_at = datetime.now().isoformat()

        if thread.title == "新对话" and message.get("role") == "user":
            query = message.get("content", "")[:30]
            thread.title = query + ("..." if len(message.get("content", "")) > 30 else "")

        self._save_conversation(agent_id, thread)
        return True

    def update_conversation(self, agent_id: str, thread_id: str,
                            updates: dict) -> ConversationThread | None:
        """Update a conversation thread (rename, etc.)."""
        thread = self.get_conversation(agent_id, thread_id)
        if not thread:
            return None
        for key, value in updates.items():
            if hasattr(thread, key) and value is not None:
                setattr(thread, key, value)
        thread.updated_at = datetime.now().isoformat()
        self._save_conversation(agent_id, thread)
        return thread

    def delete_conversation(self, agent_id: str, thread_id: str) -> bool:
        """Delete a conversation thread."""
        if agent_id not in self.conversations or thread_id not in self.conversations[agent_id]:
            return False
        del self.conversations[agent_id][thread_id]
        conv_file = self.conversations_dir / agent_id / f"{thread_id}.json"
        if conv_file.exists():
            conv_file.unlink()
        return True

    # ── Migration ────────────────────────────────────────

    def ensure_default_agent(self, llm_model: str = "qwen-plus",
                              query_history: list[dict] = None):
        """Ensure a default agent exists, migrate legacy query history."""
        has_default = any(
            a.kb_name == "default" and a.name in ("通用助手", "default")
            for a in self.agents.values()
        )
        if not has_default:
            agent = AgentConfig(
                name="通用助手", icon="🤖",
                description="默认智能体，关联默认知识库",
                welcome_message="你好！我是通用助手，可以回答知识库中的任何问题。",
                kb_name="default", llm_model=llm_model,
                system_prompt="", use_default_prompt=True,
            )
            self.create_agent(agent, owner_id=1, owner_username="admin")
            if query_history:
                thread = self.create_conversation(agent.id, title="旧查询记录")
                for record in reversed(query_history):
                    thread.messages.append({
                        "role": "user",
                        "content": record.get("query", ""),
                        "time": record.get("time", ""),
                    })
                    thread.messages.append({
                        "role": "assistant",
                        "content": record.get("answer", ""),
                        "elapsed": record.get("elapsed", 0),
                        "kb": record.get("kb", ""),
                        "mode": record.get("mode", ""),
                    })
                thread.updated_at = datetime.now().isoformat()
                self._save_conversation(agent.id, thread)
                return agent, thread
        return None, None

    def migrate_agents(self) -> int:
        """Migrate owner_id=0 agents and conversations to admin (user_id=1)."""
        count = 0
        changed = False
        for agent in self.agents.values():
            if agent.owner_id == 0:
                agent.owner_id = 1
                agent.owner_username = "admin"
                count += 1
                changed = True
        for agent_id, threads in self.conversations.items():
            for thread in threads.values():
                if thread.owner_id == 0:
                    thread.owner_id = 1
                    changed = True
        if changed:
            self._save_agents()
            for agent_id, threads in self.conversations.items():
                for thread in threads.values():
                    self._save_conversation(agent_id, thread)
            print(f"[AGENT-MIGRATE] 已将 {count} 个智能体及其对话分配给管理员", flush=True)
        return count


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


# ═══════════════════════════════════════════════════════════
# PG Dispatch Layer — async functions that auto-detect PG
# ═══════════════════════════════════════════════════════════
#
# Pattern (matches auth.py):
#   - PG available → use pg_agent_repo (PostgreSQL)
#   - PG unavailable → use AgentManager singleton (JSON file)
#
# All functions are async-safe. Sync AgentManager calls run via
# run_in_executor to avoid blocking the event loop.

def _pg_agent_ready() -> bool:
    """Check if PG agent backend is available."""
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        get_pg_pool()
        return True
    except (RuntimeError, ImportError):
        return False


# ── Agent CRUD ──────────────────────────────────────────

async def dispatch_list_agents(
    user_id: int | None = None,
    is_admin: bool = False,
) -> list[dict]:
    """List agents — PG-dispatched. Returns list of agent dicts."""
    if _pg_agent_ready():
        try:
            from raganything.services.pg_agent_repo import pg_list_agents
            return await pg_list_agents(user_id=user_id, is_admin=is_admin)
        except Exception:
            pass

    # File fallback
    import asyncio as _asyncio
    mgr = get_agent_manager()
    def _fn():
        agents = mgr.list_agents(user_id=user_id, is_admin=is_admin)
        return [a.model_dump() for a in agents]
    return await _asyncio.get_running_loop().run_in_executor(None, _fn)


async def dispatch_get_agent(agent_id: str) -> dict | None:
    """Get a single agent by ID — PG-dispatched."""
    if _pg_agent_ready():
        try:
            from raganything.services.pg_agent_repo import pg_get_agent
            result = await pg_get_agent(agent_id)
            if result:
                return result
        except Exception:
            pass

    import asyncio as _asyncio
    mgr = get_agent_manager()
    def _fn():
        agent = mgr.get_agent(agent_id)
        return agent.model_dump() if agent else None
    return await _asyncio.get_running_loop().run_in_executor(None, _fn)


async def dispatch_create_agent(
    config: dict,
    owner_id: int = 0,
    owner_username: str = "",
) -> dict:
    """Create an agent — PG-dispatched. Returns created agent dict."""
    if _pg_agent_ready():
        try:
            from raganything.services.pg_agent_repo import pg_create_agent
            return await pg_create_agent(
                config, owner_id=owner_id, owner_username=owner_username,
            )
        except Exception:
            pass

    import asyncio as _asyncio
    mgr = get_agent_manager()
    def _fn():
        agent = mgr.create_agent(config, owner_id=owner_id, owner_username=owner_username)
        return agent.model_dump()
    return await _asyncio.get_running_loop().run_in_executor(None, _fn)


async def dispatch_update_agent(agent_id: str, updates: dict) -> dict | None:
    """Update an agent — PG-dispatched. Returns updated agent dict or None."""
    if _pg_agent_ready():
        try:
            from raganything.services.pg_agent_repo import pg_update_agent
            return await pg_update_agent(agent_id, updates)
        except Exception:
            pass

    import asyncio as _asyncio
    mgr = get_agent_manager()
    def _fn():
        agent = mgr.update_agent(agent_id, updates)
        return agent.model_dump() if agent else None
    return await _asyncio.get_running_loop().run_in_executor(None, _fn)


async def dispatch_delete_agent(agent_id: str) -> bool:
    """Delete an agent — PG-dispatched. Returns True if deleted."""
    if _pg_agent_ready():
        try:
            from raganything.services.pg_agent_repo import pg_delete_agent
            return await pg_delete_agent(agent_id)
        except Exception:
            pass

    import asyncio as _asyncio
    mgr = get_agent_manager()
    return await _asyncio.get_running_loop().run_in_executor(
        None, mgr.delete_agent, agent_id,
    )


# ── Conversation CRUD ────────────────────────────────────

async def dispatch_list_conversations(
    agent_id: str,
    user_id: int | None = None,
    is_admin: bool = False,
) -> list[dict]:
    """List conversation threads — PG-dispatched."""
    if _pg_agent_ready():
        try:
            from raganything.services.pg_agent_repo import pg_list_conversations
            return await pg_list_conversations(
                agent_id, user_id=user_id, is_admin=is_admin,
            )
        except Exception:
            pass

    import asyncio as _asyncio
    mgr = get_agent_manager()
    def _fn():
        threads = mgr.list_conversations(
            agent_id, user_id=user_id, is_admin=is_admin,
        )
        return [t.model_dump() for t in threads]
    return await _asyncio.get_running_loop().run_in_executor(None, _fn)


async def dispatch_get_conversation(
    agent_id: str, thread_id: str,
) -> dict | None:
    """Get a conversation thread with messages — PG-dispatched."""
    if _pg_agent_ready():
        try:
            from raganything.services.pg_agent_repo import pg_get_conversation
            return await pg_get_conversation(agent_id, thread_id)
        except Exception:
            pass

    import asyncio as _asyncio
    mgr = get_agent_manager()
    def _fn():
        thread = mgr.get_conversation(agent_id, thread_id)
        return thread.model_dump() if thread else None
    return await _asyncio.get_running_loop().run_in_executor(None, _fn)


async def dispatch_create_conversation(
    agent_id: str,
    title: str = "新对话",
    owner_id: int = 0,
) -> dict:
    """Create a conversation thread — PG-dispatched."""
    if _pg_agent_ready():
        try:
            from raganything.services.pg_agent_repo import pg_create_conversation
            return await pg_create_conversation(agent_id, title=title, owner_id=owner_id)
        except Exception:
            pass

    import asyncio as _asyncio
    mgr = get_agent_manager()
    def _fn():
        thread = mgr.create_conversation(agent_id, title=title, owner_id=owner_id)
        return thread.model_dump()
    return await _asyncio.get_running_loop().run_in_executor(None, _fn)


async def dispatch_add_message(
    agent_id: str, thread_id: str, message: dict,
) -> bool:
    """Add a message to a conversation — PG-dispatched."""
    if _pg_agent_ready():
        try:
            from raganything.services.pg_agent_repo import pg_add_message
            return await pg_add_message(agent_id, thread_id, message)
        except Exception:
            pass

    import asyncio as _asyncio
    mgr = get_agent_manager()
    return await _asyncio.get_running_loop().run_in_executor(
        None, mgr.add_message, agent_id, thread_id, message,
    )


async def dispatch_delete_conversation(
    agent_id: str, thread_id: str,
) -> bool:
    """Delete a conversation — PG-dispatched."""
    if _pg_agent_ready():
        try:
            from raganything.services.pg_agent_repo import pg_delete_conversation
            return await pg_delete_conversation(agent_id, thread_id)
        except Exception:
            pass

    import asyncio as _asyncio
    mgr = get_agent_manager()
    return await _asyncio.get_running_loop().run_in_executor(
        None, mgr.delete_conversation, agent_id, thread_id,
    )


async def dispatch_update_conversation(
    agent_id: str, thread_id: str, updates: dict,
) -> dict | None:
    """Update a conversation — PG-dispatched."""
    if _pg_agent_ready():
        try:
            from raganything.services.pg_agent_repo import pg_update_conversation
            return await pg_update_conversation(agent_id, thread_id, updates)
        except Exception:
            pass

    import asyncio as _asyncio
    mgr = get_agent_manager()
    def _fn():
        thread = mgr.update_conversation(agent_id, thread_id, updates)
        return thread.model_dump() if thread else None
    return await _asyncio.get_running_loop().run_in_executor(None, _fn)

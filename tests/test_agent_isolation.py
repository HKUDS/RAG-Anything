"""agent_manager.py 数据隔离测试"""
import pytest
import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_manager import (
    AgentConfig,
    ConversationThread,
    AgentManager,
)


class TestAgentOwnership:
    """Agent 所有权与数据隔离"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        # 创建干净的 agent_meta.json
        agent_meta = Path(self.tmpdir) / "agent_meta.json"
        agent_meta.write_text('{"agents": [], "updated_at": ""}')
        self.mgr = AgentManager(self.tmpdir)

    def test_create_agent_injects_owner(self):
        agent = self.mgr.create_agent(
            AgentConfig(name="test1", kb_name="default"),
            owner_id=42, owner_username="alice",
        )
        assert agent.owner_id == 42
        assert agent.owner_username == "alice"

    def test_list_agents_filters_by_owner(self):
        # 创建 admin 的 agent
        self.mgr.create_agent(
            AgentConfig(name="admin_agent", kb_name="default"),
            owner_id=1, owner_username="admin",
        )
        # 创建 alice 的 agent
        self.mgr.create_agent(
            AgentConfig(name="alice_agent", kb_name="default"),
            owner_id=42, owner_username="alice",
        )

        # Alice 只能看到自己的 + 系统级
        alice_agents = self.mgr.list_agents(user_id=42, is_admin=False)
        assert len(alice_agents) == 1
        assert alice_agents[0].name == "alice_agent"

        # Admin 看到全部
        admin_agents = self.mgr.list_agents(user_id=1, is_admin=True)
        assert len(admin_agents) == 2

    def test_system_agent_visible_to_all(self):
        # 系统级 agent (owner_id=0)
        self.mgr.create_agent(
            AgentConfig(name="system_agent", kb_name="default"),
            owner_id=0,
        )
        alice_agents = self.mgr.list_agents(user_id=42, is_admin=False)
        assert len(alice_agents) == 1
        assert alice_agents[0].name == "system_agent"


class TestConversationOwnership:
    """对话线程所有权与隔离"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        agent_meta = Path(self.tmpdir) / "agent_meta.json"
        agent_meta.write_text('{"agents": [], "updated_at": ""}')
        self.mgr = AgentManager(self.tmpdir)
        self.agent = self.mgr.create_agent(
            AgentConfig(name="test_agent"),
            owner_id=1, owner_username="admin",
        )

    def test_create_conversation_injects_owner(self):
        thread = self.mgr.create_conversation(
            self.agent.id, title="test_thread", owner_id=42,
        )
        assert thread.owner_id == 42

    def test_list_conversations_filters_by_owner(self):
        self.mgr.create_conversation(self.agent.id, title="alice_thread", owner_id=42)
        self.mgr.create_conversation(self.agent.id, title="bob_thread", owner_id=99)

        alice_threads = self.mgr.list_conversations(
            self.agent.id, user_id=42, is_admin=False,
        )
        assert len(alice_threads) == 1
        assert alice_threads[0].title == "alice_thread"

        # Admin sees all
        admin_threads = self.mgr.list_conversations(
            self.agent.id, user_id=1, is_admin=True,
        )
        assert len(admin_threads) == 2

    def test_migrate_agents(self):
        # 创建无主 agent（模拟旧数据）
        old_agent = self.mgr.create_agent(
            AgentConfig(name="old_agent"),
            owner_id=0,
        )
        count = self.mgr.migrate_agents()
        assert count >= 1
        # 迁移后 agent 归 admin
        migrated = self.mgr.get_agent(old_agent.id)
        assert migrated.owner_id == 1
        assert migrated.owner_username == "admin"

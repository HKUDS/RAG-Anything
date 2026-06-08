"""
RAG-Anything 智能体管理器
智能体 = 知识库 + 模型配置 + 分块策略 + 对话历史

存储: ./agent_meta.json (智能体元数据)
      ./agent_conversations/ (对话线程)
"""
from __future__ import annotations

import json
import uuid
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

class AgentConfig(BaseModel):
    """智能体配置"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "新智能体"
    icon: str = "🤖"  # emoji 图标
    description: str = ""
    welcome_message: str = "你好！我是你的智能助手，有什么可以帮你的？"

    # 知识库
    kb_name: str = "default"  # 关联的知识库名称

    # 模型配置
    llm_model: str = "qwen-plus"
    temperature: float = 0.0
    max_response_tokens: int = 4096

    # 检索配置
    query_mode: str = "hybrid"  # hybrid/local/global/naive
    retrieval_top_k: int = 40
    chunk_top_k: int = 20
    enable_rerank: bool = False
    include_references: bool = True

    # 提示词
    system_prompt: str = ""
    use_default_prompt: bool = True  # 是否叠加默认的格式化 prompt

    # 元数据
    template_id: str = ""  # 从哪个模板创建的
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ConversationThread(BaseModel):
    """对话线程"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = "新对话"
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    messages: list[dict] = Field(default_factory=list)  # [{role, content, thinking, elapsed}]


# ═══════════════════════════════════════════════════════════
# 智能体管理器
# ═══════════════════════════════════════════════════════════

class AgentManager:
    """智能体管理器：CRUD + 持久化"""

    def __init__(self, data_dir: str = "."):
        self.data_dir = Path(data_dir)
        self.meta_file = self.data_dir / "agent_meta.json"
        self.conversations_dir = self.data_dir / "agent_conversations"

        # 内存缓存
        self.agents: dict[str, AgentConfig] = {}
        self.conversations: dict[str, dict[str, ConversationThread]] = {}  # agent_id -> {thread_id -> thread}

        self._load()

    # ── 持久化 ──────────────────────────────────────

    def _load(self):
        """从磁盘加载智能体和对话"""
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

        # 加载对话线程
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
        """持久化智能体元数据（原子写入）"""
        import tempfile as _tempfile
        data = {
            "agents": [agent.model_dump() for agent in self.agents.values()],
            "updated_at": datetime.now().isoformat(),
        }
        tmp = self.meta_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.meta_file)  # 原子替换

    def _save_conversation(self, agent_id: str, thread: ConversationThread):
        """持久化单个对话线程（原子写入）"""
        conv_dir = self.conversations_dir / agent_id
        conv_dir.mkdir(parents=True, exist_ok=True)
        conv_file = conv_dir / f"{thread.id}.json"
        tmp = conv_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(thread.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(conv_file)  # 原子替换

    # ── 智能体 CRUD ─────────────────────────────────

    def list_agents(self) -> list[AgentConfig]:
        """列出所有智能体，按更新时间倒序"""
        return sorted(
            self.agents.values(),
            key=lambda a: a.updated_at,
            reverse=True,
        )

    def get_agent(self, agent_id: str) -> AgentConfig | None:
        """获取单个智能体"""
        return self.agents.get(agent_id)

    def create_agent(self, config: AgentConfig | dict) -> AgentConfig:
        """创建智能体"""
        if isinstance(config, dict):
            config = AgentConfig(**config)
        if not config.id:
            config.id = str(uuid.uuid4())[:8]
        config.created_at = config.created_at or datetime.now().isoformat()
        config.updated_at = config.created_at
        self.agents[config.id] = config
        self._save_agents()
        return config

    def update_agent(self, agent_id: str, updates: dict) -> AgentConfig | None:
        """更新智能体配置"""
        agent = self.agents.get(agent_id)
        if not agent:
            return None
        # 部分更新
        for key, value in updates.items():
            if hasattr(agent, key) and value is not None:
                setattr(agent, key, value)
        agent.updated_at = datetime.now().isoformat()
        self.agents[agent_id] = agent
        self._save_agents()
        return agent

    def delete_agent(self, agent_id: str) -> bool:
        """删除智能体及其所有对话"""
        if agent_id not in self.agents:
            return False
        del self.agents[agent_id]
        self._save_agents()

        # 删除对话目录
        if agent_id in self.conversations:
            conv_dir = self.conversations_dir / agent_id
            if conv_dir.exists():
                shutil.rmtree(conv_dir, ignore_errors=True)
            del self.conversations[agent_id]

        return True

    # ── 对话线程管理 ────────────────────────────────

    def list_conversations(self, agent_id: str) -> list[ConversationThread]:
        """列出智能体的所有对话线程"""
        threads = self.conversations.get(agent_id, {})
        return sorted(threads.values(), key=lambda t: t.updated_at, reverse=True)

    def get_conversation(self, agent_id: str, thread_id: str) -> ConversationThread | None:
        """获取单个对话线程"""
        return self.conversations.get(agent_id, {}).get(thread_id)

    def create_conversation(self, agent_id: str, title: str = "新对话") -> ConversationThread:
        """创建新对话线程"""
        thread = ConversationThread(
            id=str(uuid.uuid4())[:8],
            title=title,
        )
        if agent_id not in self.conversations:
            self.conversations[agent_id] = {}
        self.conversations[agent_id][thread.id] = thread
        self._save_conversation(agent_id, thread)
        return thread

    def add_message(self, agent_id: str, thread_id: str, message: dict) -> bool:
        """向对话线程添加消息"""
        thread = self.get_conversation(agent_id, thread_id)
        if not thread:
            return False
        thread.messages.append(message)
        thread.updated_at = datetime.now().isoformat()

        # 自动用第一条用户消息重命名线程
        if thread.title == "新对话" and message.get("role") == "user":
            query = message.get("content", "")[:30]
            thread.title = query + ("..." if len(message.get("content", "")) > 30 else "")

        self._save_conversation(agent_id, thread)
        return True

    def update_conversation(self, agent_id: str, thread_id: str,
                            updates: dict) -> ConversationThread | None:
        """更新对话线程（重命名等）"""
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
        """删除对话线程"""
        if agent_id not in self.conversations or thread_id not in self.conversations[agent_id]:
            return False
        del self.conversations[agent_id][thread_id]
        # 删除文件
        conv_file = self.conversations_dir / agent_id / f"{thread_id}.json"
        if conv_file.exists():
            conv_file.unlink()
        return True

    # ── 迁移 ────────────────────────────────────────

    def ensure_default_agent(self, llm_model: str = "qwen-plus",
                              query_history: list[dict] = None):
        """确保存在默认智能体，迁移旧数据"""
        has_default = any(a.kb_name == "default" and a.name in ("通用助手", "default")
                         for a in self.agents.values())
        if not has_default:
            agent = AgentConfig(
                name="通用助手",
                icon="🤖",
                description="默认智能体，关联默认知识库",
                welcome_message="你好！我是通用助手，可以回答知识库中的任何问题。",
                kb_name="default",
                llm_model=llm_model,
                system_prompt="",
                use_default_prompt=True,
            )
            self.create_agent(agent)
            # 迁移旧查询历史到默认智能体
            if query_history:
                thread = self.create_conversation(agent.id, title="旧查询记录")
                for record in reversed(query_history):  # 倒序恢复时间顺序
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


# 全局单例
agent_manager: AgentManager | None = None


def init_agent_manager(data_dir: str = ".") -> AgentManager:
    """初始化全局智能体管理器"""
    global agent_manager
    agent_manager = AgentManager(data_dir)
    return agent_manager


def get_agent_manager() -> AgentManager:
    """获取全局智能体管理器"""
    if agent_manager is None:
        return init_agent_manager()
    return agent_manager

import streamlit as st
import streamlit.components.v1 as components
import os
import sys
import asyncio
import json
import time
import hashlib
import threading
import socket
import subprocess
import signal
import tempfile
import atexit
from pathlib import Path


def load_env_file(env_path: Path):
    """Load .env key-value pairs into process environment if not already set."""
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key:
            continue

        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]

        os.environ.setdefault(key, value)


def get_env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        print(f"Invalid integer for {name}: {value}. Using default={default}")
        return default


def get_env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    print(f"Invalid boolean for {name}: {value}. Using default={default}")
    return default


load_env_file(Path(__file__).resolve().parent / ".env")


def _child_pid_registry_path() -> Path:
    return Path(tempfile.gettempdir()) / f"ppt_rag_streamlit_children_{os.getpid()}.json"


def _load_child_pids() -> list[int]:
    registry_path = _child_pid_registry_path()
    if not registry_path.exists():
        return []
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [int(pid) for pid in data if isinstance(pid, int) or str(pid).isdigit()]
    except Exception:
        return []


def _save_child_pids(pids: list[int]):
    registry_path = _child_pid_registry_path()
    unique_sorted_pids = sorted(set(pids))
    registry_path.write_text(json.dumps(unique_sorted_pids, ensure_ascii=False), encoding="utf-8")


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _register_child_pid(pid: int):
    current = _load_child_pids()
    current.append(pid)
    _save_child_pids(current)


def _cleanup_spawned_children():
    pids = _load_child_pids()
    if not pids:
        return

    # 子进程使用 start_new_session=True，pid 同时是其进程组 id。
    for pid in pids:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass

    deadline = time.time() + 2.0
    while time.time() < deadline:
        if not any(_is_process_alive(pid) for pid in pids):
            break
        time.sleep(0.1)

    for pid in pids:
        if not _is_process_alive(pid):
            continue
        try:
            os.killpg(pid, signal.SIGKILL)
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass

    try:
        _child_pid_registry_path().unlink(missing_ok=True)
    except Exception:
        pass


def _register_cleanup_handlers_once():
    marker_key = "PPT_RAG_CHILD_CLEANUP_REGISTERED_PID"
    current_pid = str(os.getpid())
    if os.environ.get(marker_key) == current_pid:
        return
    os.environ[marker_key] = current_pid

    # Always register atexit cleanup; this is safe in Streamlit script threads.
    atexit.register(_cleanup_spawned_children)

    # Streamlit may execute user code outside the main thread.
    # signal.signal(...) only works in the main thread of the main interpreter.
    if threading.current_thread() is not threading.main_thread():
        return

    previous_sigint_handler = signal.getsignal(signal.SIGINT)
    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)

    def _signal_handler(signum, frame):
        _cleanup_spawned_children()

        previous_handler = (
            previous_sigint_handler if signum == signal.SIGINT else previous_sigterm_handler
        )
        if callable(previous_handler):
            previous_handler(signum, frame)
            return
        if previous_handler == signal.SIG_IGN:
            return
        if signum == signal.SIGINT:
            raise KeyboardInterrupt
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    except ValueError:
        # Fallback: if runtime context still disallows signal registration,
        # rely on atexit cleanup only.
        pass


_register_cleanup_handlers_once()

# App config from environment
OPENAI_API_KEY = get_env_str("OPENAI_API_KEY", "")
OPENAI_BASE_URL = get_env_str("OPENAI_BASE_URL", "https://api.yunwu.ai/v1")

TEXT_LLM_MODEL = get_env_str("TEXT_LLM_MODEL", "gpt-4o-mini")
VISION_LLM_MODEL = get_env_str("VISION_LLM_MODEL", "gpt-4o")
AGENT_PROVIDER = get_env_str("AGENT_PROVIDER", "openai").strip().lower()
AGENT_MODEL = get_env_str("AGENT_MODEL", "gpt-4o")
LITELLM_API_KEY = get_env_str("LITELLM_API_KEY", "")
LITELLM_BASE_URL = get_env_str("LITELLM_BASE_URL", "")
LITELLM_PROVIDER_NAME = get_env_str("LITELLM_PROVIDER_NAME", "").strip().lower()

EMBEDDING_MODEL = get_env_str("EMBEDDING_MODEL", "text-embedding-3-large")
EMBEDDING_DIM = get_env_int("EMBEDDING_DIM", 3072)
EMBEDDING_MAX_TOKEN_SIZE = get_env_int("EMBEDDING_MAX_TOKEN_SIZE", 8192)

PARSER = get_env_str("PARSER", "mineru")
PARSE_METHOD = get_env_str("PARSE_METHOD", "auto")

ENABLE_IMAGE_PROCESSING = get_env_bool("ENABLE_IMAGE_PROCESSING", True)
ENABLE_TABLE_PROCESSING = get_env_bool("ENABLE_TABLE_PROCESSING", True)
ENABLE_EQUATION_PROCESSING = get_env_bool("ENABLE_EQUATION_PROCESSING", True)

RETRIEVE_TOP_K = get_env_int("RETRIEVE_TOP_K", 20)
RETRIEVE_CHUNK_TOP_K = get_env_int("RETRIEVE_CHUNK_TOP_K", 20)

OUTPUT_DIR = get_env_str("OUTPUT_DIR", "./output")
DOC_STORE_DIR = get_env_str("DOC_STORE_DIR", "./uploaded_docs")
WORKING_DIR_ROOT = get_env_str("WORKING_DIR_ROOT", "./rag_storage_by_file")
REGISTRY_PATH = get_env_str("REGISTRY_PATH", "./uploaded_docs_registry.json")

# ==========================================
# 🛠️ 1. 环境自检与导包 (Environment Check)
# ==========================================
# 确保当前目录在 sys.path 中，防止 import 报错
current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    # 尝试引入后端引擎
    from lightrag.llm.openai import openai_complete_if_cache, openai_embed
    from lightrag.utils import EmbeddingFunc
    from raganything import RAGAnything, RAGAnythingConfig
    from rag_agent.llm import OpenAIProvider, LiteLLMProvider
    from rag_agent.agent.loop import AgentLoop
except ImportError as e:
    st.error(f"❌ 严重错误：无法导入 RAG-Anything 库！\n请确保 app.py 位于项目根目录下。\n详细报错: {e}")
    st.stop()

# ==========================================
# 🎨 2. 页面配置 (Page Config)
# ==========================================
st.set_page_config(
    page_title="RAG-Anything Pro (Single Doc Edition)", 
    page_icon="📚", 
    layout="wide"
)

# ==========================================
# 🧠 3. 核心引擎服务 (Service Layer)
# ==========================================
class RAGService:
    """
    RAG 服务封装类：
    负责管理 RAGAnything 实例，确保模型常驻内存，
    避免每次操作都重新加载模型。
    """
    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url
        self.engine_pool = {}
        self.agent_loop_pool = {}

    def get_engine(self, working_dir):
        """单进程仅允许创建一次 rag_instance，不允许切换文档。"""
        if working_dir in self.engine_pool:
            return self.engine_pool[working_dir]

        if self.engine_pool:
            existing_working_dir = next(iter(self.engine_pool.keys()))
            raise RuntimeError(
                "当前进程已创建 rag_instance，禁止切换文档。"
                f"当前缓存目录: {existing_working_dir}；目标缓存目录: {working_dir}。"
                "如需更改文件，请重启进程后再操作。"
            )

        os.makedirs(working_dir, exist_ok=True)

        # === 1. 配置参数 ===
        config = RAGAnythingConfig(
            working_dir=working_dir,
            parser=PARSER,
            parse_method=PARSE_METHOD,
            enable_image_processing=ENABLE_IMAGE_PROCESSING,
            enable_table_processing=ENABLE_TABLE_PROCESSING,
            enable_equation_processing=ENABLE_EQUATION_PROCESSING,
        )

        # === 2. 定义 LLM 调用函数 ===
        def llm_model_func(prompt, system_prompt=None, history_messages=[], **kwargs):
            return openai_complete_if_cache(
                TEXT_LLM_MODEL,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                api_key=self.api_key,
                base_url=self.base_url,
                **kwargs,
            )

        # === 3. 定义 Embedding 函数 ===
        embedding_func = EmbeddingFunc(
            embedding_dim=EMBEDDING_DIM,
            max_token_size=EMBEDDING_MAX_TOKEN_SIZE,
            func=lambda texts: openai_embed(
                texts,
                model=EMBEDDING_MODEL,
                api_key=self.api_key,
                base_url=self.base_url,
            ),
        )

        # === 4. 定义视觉模型函数 (Vision) ===
        def vision_model_func(
            prompt, system_prompt=None, history_messages=[], image_data=None, messages=None, **kwargs
        ):
            if messages:
                return openai_complete_if_cache(
                    VISION_LLM_MODEL,
                    "",
                    system_prompt=None,
                    history_messages=[],
                    messages=messages,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    **kwargs,
                )
            elif image_data:
                return openai_complete_if_cache(
                    VISION_LLM_MODEL,
                    "",
                    system_prompt=None,
                    history_messages=[],
                    messages=[
                        {"role": "system", "content": system_prompt} if system_prompt else None,
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
                                },
                            ],
                        }
                        if image_data
                        else {"role": "user", "content": prompt},
                    ],
                    api_key=self.api_key,
                    base_url=self.base_url,
                    **kwargs,
                )
            else:
                return llm_model_func(prompt, system_prompt, history_messages, **kwargs)

        # === 5. 实例化引擎 ===
        rag_instance = RAGAnything(
            config=config,
            llm_model_func=llm_model_func,
            vision_model_func=vision_model_func,
            embedding_func=embedding_func,
        )
        self.engine_pool[working_dir] = rag_instance
        return rag_instance

    def get_agent_loop(self, working_dir):
        """按 working_dir 复用 AgentLoop，确保同一文档会话连续。"""
        if working_dir in self.agent_loop_pool:
            return self.agent_loop_pool[working_dir]

        rag_instance = self.get_engine(working_dir)
        provider = self._build_agent_provider()
        agent_workspace = os.path.join(working_dir, "agent_loop_workspace")
        os.makedirs(agent_workspace, exist_ok=True)

        loop = AgentLoop(
            provider=provider,
            workspace=agent_workspace,
            rag=rag_instance,
            model=AGENT_MODEL,
            retrieve_config={
                "mode": "hybrid",
                "top_k": RETRIEVE_TOP_K,
                "chunk_top_k": RETRIEVE_CHUNK_TOP_K,
            },
        )
        self.agent_loop_pool[working_dir] = loop
        return loop

    def _build_agent_provider(self):
        if AGENT_PROVIDER == "openai":
            if OpenAIProvider is None:
                raise RuntimeError("OpenAIProvider 不可用，请检查 rag_agent.llm 导入。")
            return OpenAIProvider(
                api_key=self.api_key,
                api_base=self.base_url,
                default_model=AGENT_MODEL,
            )

        if AGENT_PROVIDER == "litellm":
            if LiteLLMProvider is None:
                raise RuntimeError("LiteLLMProvider 不可用，请安装 litellm 并检查 rag_agent.llm 导入。")
            litellm_key = LITELLM_API_KEY or self.api_key
            litellm_base = LITELLM_BASE_URL or self.base_url
            litellm_provider_name = LITELLM_PROVIDER_NAME or None
            return LiteLLMProvider(
                api_key=litellm_key,
                api_base=litellm_base,
                default_model=AGENT_MODEL,
                provider_name=litellm_provider_name,
            )

        raise RuntimeError(
            f"不支持的 AGENT_PROVIDER: {AGENT_PROVIDER}。请使用 'openai' 或 'litellm'。"
        )

# 异步运行辅助函数 (固定单事件循环，避免跨 loop 报错)
@st.cache_resource(show_spinner=False)
def get_async_runtime():
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def _run_loop():
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=_run_loop, daemon=True, name="rag-streamlit-async-loop")
    thread.start()
    ready.wait()
    return loop, thread


def run_async(coro):
    loop, _ = get_async_runtime()
    if loop.is_closed():
        get_async_runtime.clear()
        loop, _ = get_async_runtime()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex((host, port)) != 0


def find_available_port(start_port: int = 8502, max_tries: int = 100) -> int:
    for port in range(start_port, start_port + max_tries):
        if is_port_available(port):
            return port
    raise RuntimeError("未找到可用端口，请手动释放端口后重试。")


def launch_streamlit_process(port: int):
    app_path = Path(__file__).resolve()
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(port),
        "--server.headless",
        "true",
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(app_path.parent),
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _register_child_pid(proc.pid)

# ==========================================
# 🖥️ 4. 前端界面逻辑 (UI Logic)
# ==========================================

# 初始化 Session State
if "rag_service" not in st.session_state:
    st.session_state.rag_service = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "doc_indexed" not in st.session_state:
    st.session_state.doc_indexed = False
if "current_doc_name" not in st.session_state:
    st.session_state.current_doc_name = ""
if "current_working_dir" not in st.session_state:
    st.session_state.current_working_dir = ""
if "current_file_path" not in st.session_state:
    st.session_state.current_file_path = ""
if "post_parse_success_message" not in st.session_state:
    st.session_state.post_parse_success_message = ""

# 固定文档存储目录（用于复用缓存）
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx", ".pptx"}
os.makedirs(DOC_STORE_DIR, exist_ok=True)
os.makedirs(WORKING_DIR_ROOT, exist_ok=True)


def load_registry():
    if not os.path.exists(REGISTRY_PATH):
        return {}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_registry(registry):
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def compute_file_sha256(file_path):
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def resolve_working_dir_for_file(file_path):
    abs_path = str(Path(file_path).resolve())
    file_hash = compute_file_sha256(abs_path)
    working_dir = os.path.join(WORKING_DIR_ROOT, file_hash)

    registry = load_registry()
    registry[abs_path] = {
        "file_name": os.path.basename(abs_path),
        "file_hash": file_hash,
        "working_dir": working_dir,
        "updated_at": int(time.time()),
    }
    save_registry(registry)

    return file_hash, working_dir

# --- 侧边栏 ---
with st.sidebar:
    st.title("📚 RAG 单文档问答器")
    st.caption("Single Document Parse + QA")
    st.divider()
    
    # 配置区域
    if OPENAI_API_KEY:
        st.caption("API Key: loaded from .env")
    else:
        st.caption("API Key: missing in .env")
    st.caption(f"Base URL (.env): {OPENAI_BASE_URL}")

    if st.session_state.post_parse_success_message:
        st.success(st.session_state.post_parse_success_message)
        st.session_state.post_parse_success_message = ""

    if st.button("🧩 新建rag实例"):
        try:
            new_port = find_available_port()
            launch_streamlit_process(new_port)
            st.success(f"已启动新进程，端口: {new_port}")
            st.markdown(f"[打开新进程页面](http://localhost:{new_port})")
            components.html(
                                f"""
                                <script>
                                    const target = 'http://localhost:{new_port}';
                                    const opened = window.open(target, '_blank');
                                    if (!opened) {{
                                        try {{
                                            window.top.location.href = target;
                                        }} catch (e) {{
                                            // Keep manual link as fallback.
                                        }}
                                    }}
                                </script>
                                """,
                height=0,
            )
        except Exception as e:
            st.error(f"新开进程失败: {str(e)}")
    
    st.divider()
    
    selected_file_path = None
    selected_file_name = None
    has_existing_engine = bool(
        st.session_state.rag_service and st.session_state.rag_service.engine_pool
    )

    if has_existing_engine:
        if st.session_state.current_doc_name:
            st.info(f"当前文档：{st.session_state.current_doc_name}")
        selected_file_path = st.session_state.current_file_path or None
        selected_file_name = st.session_state.current_doc_name or ""
    else:
        # 单文档入口（上传新文件 / 选择已有文件）
        source_mode = st.radio(
            "文档来源",
            ["上传新文件", "选择已有文件"],
            horizontal=True,
        )

        if source_mode == "上传新文件":
            uploaded_file = st.file_uploader(
                "📄 上传一个文档进行解析",
                type=['pdf', 'txt', 'docx', 'pptx'],
                accept_multiple_files=False
            )

            if uploaded_file is not None:
                target_path = os.path.join(DOC_STORE_DIR, uploaded_file.name)

                # 若同名文件已存在且内容相同，则不重复写入，保留原mtime以便缓存命中
                new_bytes = uploaded_file.getvalue()
                if os.path.exists(target_path):
                    with open(target_path, "rb") as f:
                        old_bytes = f.read()
                    if old_bytes != new_bytes:
                        stem = Path(uploaded_file.name).stem
                        suffix = Path(uploaded_file.name).suffix
                        idx = 1
                        while True:
                            candidate = os.path.join(DOC_STORE_DIR, f"{stem}_{idx}{suffix}")
                            if not os.path.exists(candidate):
                                target_path = candidate
                                break
                            idx += 1

                if not os.path.exists(target_path):
                    with open(target_path, "wb") as f:
                        f.write(new_bytes)

                selected_file_path = target_path
                selected_file_name = os.path.basename(target_path)
                st.info(f"已固定存储：{selected_file_name}")

        else:
            existing_files = sorted(
                [
                    f for f in os.listdir(DOC_STORE_DIR)
                    if os.path.isfile(os.path.join(DOC_STORE_DIR, f))
                    and Path(f).suffix.lower() in ALLOWED_EXTENSIONS
                ]
            )

            if existing_files:
                selected_file_name = st.selectbox("📚 选择已上传文档", existing_files)
                selected_file_path = os.path.join(DOC_STORE_DIR, selected_file_name)
                st.info(f"将使用已存储文件：{selected_file_name}")

                confirm_delete = st.checkbox("确认删除当前选中文档", key="confirm_delete_existing_file")
                if st.button("🗑️ 删除当前选中文档"):
                    if not confirm_delete:
                        st.warning("请先勾选确认删除。")
                    else:
                        try:
                            os.remove(selected_file_path)
                            abs_deleted_path = str(Path(selected_file_path).resolve())
                            registry = load_registry()
                            if abs_deleted_path in registry:
                                registry.pop(abs_deleted_path)
                                save_registry(registry)

                            if st.session_state.current_doc_name == selected_file_name:
                                st.session_state.doc_indexed = False
                                st.session_state.current_doc_name = ""
                                st.session_state.current_working_dir = ""
                                st.session_state.current_file_path = ""
                                st.session_state.messages = []
                            st.success(f"已删除：{selected_file_name}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"删除失败: {str(e)}")
            else:
                st.warning("固定目录中暂无可用文档，请先上传新文件。")

    if selected_file_path:
        _, planned_working_dir = resolve_working_dir_for_file(selected_file_path)
        st.caption(f"缓存目录：{planned_working_dir}")

        current_service = st.session_state.rag_service
        has_existing_engine = bool(current_service and current_service.engine_pool)
        existing_working_dir = ""
        if has_existing_engine:
            existing_working_dir = next(iter(current_service.engine_pool.keys()), "")
        switching_file_blocked = has_existing_engine and existing_working_dir != planned_working_dir
        if switching_file_blocked:
            st.warning("当前进程已创建 rag_instance，不允许更改文件。请重启进程后再选择新文件。")

        if st.button("🚀 解析并注入知识库", disabled=switching_file_blocked):
            if not OPENAI_API_KEY:
                st.error("未读取到 OPENAI_API_KEY，请先在 .env 中配置后重试。")
                st.stop()

            if st.session_state.rag_service is None:
                st.session_state.rag_service = RAGService(OPENAI_API_KEY, OPENAI_BASE_URL)

            file_hash, working_dir = resolve_working_dir_for_file(selected_file_path)
            engine = st.session_state.rag_service.get_engine(working_dir)

            try:
                with st.spinner("正在解析文档，请稍候..."):
                    print(f"开始解析文档: {selected_file_path}")
                    run_async(engine.process_document_complete_with_page_topics(
                        file_path=selected_file_path,
                        output_dir=OUTPUT_DIR,
                        parse_method=PARSE_METHOD
                    ))
                st.session_state.doc_indexed = True
                st.session_state.current_doc_name = selected_file_name
                st.session_state.current_working_dir = working_dir
                st.session_state.current_file_path = selected_file_path
                st.session_state.post_parse_success_message = (
                    f"✅ 解析完成：{selected_file_name}，现在可以问答了。"
                )
                st.rerun()
            except Exception as e:
                st.session_state.doc_indexed = False
                st.error(f"处理失败: {str(e)}")

# --- 主聊天界面 ---
st.subheader("💬 知识库问答")
if st.session_state.current_doc_name:
    st.caption(f"当前知识库文档：{st.session_state.current_doc_name}")

# 回显历史消息
for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

# 处理输入
if prompt := st.chat_input("基于文档内容提问..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)
    
    if st.session_state.rag_service and st.session_state.doc_indexed:
        if not st.session_state.current_working_dir:
            st.error("当前文档未绑定缓存目录，请先重新解析文档。")
            st.stop()

        with st.chat_message("assistant"):
            with st.spinner("思考中..."):
                # 基于 AgentLoop 的问答接口
                print(f"用户提问: {prompt}")
                agent_loop = st.session_state.rag_service.get_agent_loop(st.session_state.current_working_dir)
                result = run_async(
                    agent_loop.process_message(
                        prompt,
                        file_path=st.session_state.current_file_path,
                        parse_method=PARSE_METHOD,
                    )
                )
                response = result.final_answer or ""
                st.write(response)
                if result.tools_used:
                    st.caption(f"工具调用: {', '.join(result.tools_used)}")
        st.session_state.messages.append({"role": "assistant", "content": str(response)})
    elif st.session_state.rag_service and not st.session_state.doc_indexed:
        st.error("请先上传并解析一个文档，再开始问答。")
    else:
        st.error("请先在左侧初始化引擎！")
import streamlit as st
import os
import sys
import asyncio
import json
import time
import hashlib
import threading
from pathlib import Path

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

    def get_engine(self, working_dir):
        """按 working_dir 复用引擎实例，避免跨文档缓存污染"""
        if working_dir in self.engine_pool:
            return self.engine_pool[working_dir]

        os.makedirs(working_dir, exist_ok=True)

        # === 1. 配置参数 ===
        config = RAGAnythingConfig(
            working_dir=working_dir,
            parser="mineru",  # 指定使用 MinerU 解析器
            parse_method="auto",
            enable_image_processing=True,
            enable_table_processing=True,
            enable_equation_processing=True,
        )

        # === 2. 定义 LLM 调用函数 ===
        def llm_model_func(prompt, system_prompt=None, history_messages=[], **kwargs):
            return openai_complete_if_cache(
                "gpt-4o-mini",
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                api_key=self.api_key,
                base_url=self.base_url,
                **kwargs,
            )

        # === 3. 定义 Embedding 函数 ===
        embedding_func = EmbeddingFunc(
            embedding_dim=3072,
            max_token_size=8192,
            func=lambda texts: openai_embed(
                texts,
                model="text-embedding-3-large",
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
                    "gpt-4o",
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
                    "gpt-4o",
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

# 固定文档存储目录（用于复用缓存）
DOC_STORE_DIR = "./uploaded_docs"
WORKING_DIR_ROOT = "./rag_storage_by_file"
REGISTRY_PATH = "./uploaded_docs_registry.json"
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
    api_key = st.text_input("API Key", type="password")
    base_url = st.text_input("Base URL", value="https://api.yunwu.ai/v1")
    
    if st.button("🔌 启动/重置引擎"):
        st.session_state.rag_service = RAGService(api_key, base_url)
        st.session_state.doc_indexed = False
        st.session_state.current_doc_name = ""
        st.session_state.current_working_dir = ""
        st.session_state.current_file_path = ""
        st.session_state.messages = []
        st.success("引擎服务已初始化，请选择文档后解析。")
    
    st.divider()
    
    # 单文档入口（上传新文件 / 选择已有文件）
    source_mode = st.radio(
        "文档来源",
        ["上传新文件", "选择已有文件"],
        horizontal=True,
    )

    selected_file_path = None
    selected_file_name = None

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

    if selected_file_path and st.session_state.rag_service:
        _, planned_working_dir = resolve_working_dir_for_file(selected_file_path)
        st.caption(f"缓存目录：{planned_working_dir}")

        if st.button("🚀 解析并注入知识库"):
            file_hash, working_dir = resolve_working_dir_for_file(selected_file_path)
            engine = st.session_state.rag_service.get_engine(working_dir)

            try:
                with st.spinner("正在解析文档，请稍候..."):
                    print(f"开始解析文档: {selected_file_path}")
                    run_async(engine.process_document_complete(
                        file_path=selected_file_path,
                        output_dir="./output",
                        parse_method="auto"
                    ))
                st.session_state.doc_indexed = True
                st.session_state.current_doc_name = selected_file_name
                st.session_state.current_working_dir = working_dir
                st.session_state.current_file_path = selected_file_path
                st.success(f"✅ 解析完成：{selected_file_name}，现在可以问答了。")
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

        engine = st.session_state.rag_service.get_engine(st.session_state.current_working_dir)
        with st.chat_message("assistant"):
            with st.spinner("思考中..."):
                # 调用问答接口
                print(f"用户提问: {prompt}")
                response = run_async(engine.aquery(prompt, mode="hybrid"))
                st.write(response)
        st.session_state.messages.append({"role": "assistant", "content": str(response)})
    elif st.session_state.rag_service and not st.session_state.doc_indexed:
        st.error("请先上传并解析一个文档，再开始问答。")
    else:
        st.error("请先在左侧初始化引擎！")
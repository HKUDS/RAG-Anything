#!/usr/bin/env python
"""Apply all server.py refactoring changes in one pass."""
import re

with open('server.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
content = ''.join(lines)
print(f"Original: {len(lines)} lines")

# ==== 1: Replace state block ====
old_state = (
    "# ── 多知识库管理 ──────────────────────────────────\n"
    "kb_instances: dict[str, RAGAnything] = {}\n"
    'active_kb: str = "default"\n'
    "processing_tasks: dict[str, dict] = {}\n"
    "query_history: list[dict] = []\n"
    "processing_events: list[dict] = []\n"
    "ws_clients: list[WebSocket] = []\n"
    "conversation_manager: Optional[ConversationManager] = None\n"
    "\n"
    'KB_META_FILE = Path("./rag_storage_kb_meta.json")\n'
    'QUERY_HISTORY_FILE = Path("./query_history.json")\n'
    'server_logger = logging.getLogger("rag_server")'
)

new_state = (
    "# ── 多知识库管理 ──────────────────────────────────\n"
    "# 共享状态：以 raganything.routers.shared 为唯一数据源\n"
    "from raganything.routers import shared as _shared_state\n"
    "\n"
    "kb_instances = _shared_state.kb_instances\n"
    "processing_tasks = _shared_state.processing_tasks\n"
    "query_history = _shared_state.query_history\n"
    "processing_events = _shared_state.processing_events\n"
    "ws_clients = _shared_state.ws_clients\n"
    "get_kb = _shared_state.get_kb\n"
    "create_rag = _shared_state.create_rag\n"
    "load_kb_meta = _shared_state.load_kb_meta\n"
    "save_kb_meta = _shared_state.save_kb_meta\n"
    "kb_dir = _shared_state.kb_dir\n"
    "load_query_history = _shared_state.load_query_history\n"
    "save_query_history = _shared_state.save_query_history\n"
    "add_event = _shared_state.add_event\n"
    "emit_progress = _shared_state.emit_progress\n"
    "ws_broadcast = _shared_state.ws_broadcast\n"
    "validate_query_input = _shared_state.validate_query_input\n"
    "extract_image_paths = _shared_state.extract_image_paths\n"
    "get_current_user = _shared_state.get_current_user\n"
    "get_admin_user = _shared_state.get_admin_user\n"
    "verify_kb_access = _shared_state.verify_kb_access\n"
    "infer_entity_type = _shared_state.infer_entity_type\n"
    "_build_citation_block = _shared_state._build_citation_block\n"
    "_get_kb_doc_list = _shared_state._get_kb_doc_list\n"
    "_fix_stuck_doc_status = _shared_state._fix_stuck_doc_status\n"
    "_process_uploaded_file = _shared_state._process_uploaded_file\n"
    "_is_thinking_msg = _shared_state._is_thinking_msg\n"
    "_translate_thinking_msg = _shared_state._translate_thinking_msg\n"
    "QUERY_SYSTEM_PROMPT = _shared_state.QUERY_SYSTEM_PROMPT\n"
    "THINKING_PATTERNS = _shared_state.THINKING_PATTERNS\n"
    "\n"
    "KB_META_FILE = _shared_state.KB_META_FILE\n"
    "QUERY_HISTORY_FILE = _shared_state.QUERY_HISTORY_FILE\n"
    "server_logger = _shared_state.server_logger\n"
    "\n"
    "# ── Router 注册 ───────────────────────────────────────\n"
    "from raganything.routers.auth import router as auth_router\n"
    "from raganything.routers.knowledge import router as knowledge_router\n"
    "from raganything.routers.agent import router as agent_router\n"
    "from raganything.routers.query import router as query_router\n"
    "from raganything.routers.admin import router as admin_router\n"
    "\n"
    'app.include_router(auth_router, prefix="/api")\n'
    'app.include_router(knowledge_router, prefix="/api")\n'
    'app.include_router(agent_router, prefix="/api")\n'
    'app.include_router(query_router, prefix="/api")\n'
    'app.include_router(admin_router, prefix="/api")'
)

assert old_state in content, "State block not found!"
content = content.replace(old_state, new_state)
print("1. State bridge + router imports: OK")

# ==== 2: Fix startup conversation_manager ====
old_conv = (
    "    # 初始化 ConversationManager（多轮对话上下文记忆）\n"
    "    global conversation_manager\n"
    '    conversations_file = os.getenv("CONVERSATIONS_FILE", "./conversations.json")\n'
    '    max_rounds = int(os.getenv("CONVERSATION_MAX_ROUNDS", "3"))\n'
    '    max_tokens = int(os.getenv("CONVERSATION_MAX_TOKENS", "2000"))\n'
    '    max_per_user = int(os.getenv("CONVERSATION_MAX_PER_USER", "50"))\n'
    "    conversation_manager = ConversationManager(\n"
    "        storage_path=conversations_file,\n"
    "        max_rounds=max_rounds,\n"
    "        max_tokens=max_tokens,\n"
    "        max_per_user=max_per_user,\n"
    "    )\n"
    "    await conversation_manager._load()\n"
)

new_conv = (
    "    # 初始化 ConversationManager（多轮对话上下文记忆）\n"
    '    conversations_file = os.getenv("CONVERSATIONS_FILE", "./conversations.json")\n'
    '    max_rounds = int(os.getenv("CONVERSATION_MAX_ROUNDS", "3"))\n'
    '    max_tokens = int(os.getenv("CONVERSATION_MAX_TOKENS", "2000"))\n'
    '    max_per_user = int(os.getenv("CONVERSATION_MAX_PER_USER", "50"))\n'
    "    _shared_state.conversation_manager = ConversationManager(\n"
    "        storage_path=conversations_file,\n"
    "        max_rounds=max_rounds,\n"
    "        max_tokens=max_tokens,\n"
    "        max_per_user=max_per_user,\n"
    "    )\n"
    "    await _shared_state.conversation_manager._load()\n"
    "    server_logger.info(f\"ConversationManager: {_shared_state.conversation_manager.get_stats()}\")\n"
)

# Match the old_conv block (the print line comes after it in the original)
for start_line in range(len(lines)):
    if 'global conversation_manager' in lines[start_line]:
        # Find the print line after the ConversationManager block
        for end_line in range(start_line, min(start_line+20, len(lines))):
            if 'print(f"' in lines[end_line] and 'ConversationManager' in lines[end_line]:
                old_block = ''.join(lines[start_line:end_line+1])
                assert 'global conversation_manager' in old_block
                content = content.replace(old_block, new_conv)
                print("2. Startup conversation_manager: OK")
                break
        break

# ==== 3: Fix active_kb references ====
content = content.replace(
    "        global active_kb\n        active_kb = personal_kb",
    "        _shared_state.active_kb = personal_kb"
)
content = content.replace(
    "    name = name or active_kb",
    "    name = name or _shared_state.active_kb"
)
print("3. active_kb references: OK")

# ==== 4: Find boundaries for stripping ====
lines = content.split('\n')
router_end = lifecycle_start = lifecycle_end = main_start = None
first_route = None

for i, line in enumerate(lines):
    if router_end is None and 'include_router(admin_router' in line:
        router_end = i
    if lifecycle_start is None and 'on_event' in line and 'startup' in line:
        lifecycle_start = i
    if first_route is None and '@app.get("/api/files/image")' in line:
        first_route = i
    if main_start is None and line.strip().startswith('if __name__'):
        main_start = i

# Find shutdown end
in_shutdown = False
shutdown_indent = None
for i in range(lifecycle_start or 0, len(lines)):
    if 'async def shutdown' in lines[i]:
        in_shutdown = True
        shutdown_indent = len(lines[i]) - len(lines[i].lstrip())
        continue
    if in_shutdown and lifecycle_end is None:
        stripped = lines[i].strip()
        indent = len(lines[i]) - len(lines[i].lstrip())
        if stripped and indent <= shutdown_indent:
            lifecycle_end = i - 1
            break

# ==== 5: Strip dead code: keep 0..router_end + lifecycle + main_start ====
new_lines = lines[:router_end+1] + ['\n'] + lines[lifecycle_start:lifecycle_end+1] + ['\n', '\n'] + lines[main_start:]
content = '\n'.join(new_lines)

# ==== 6: Convert print() to server_logger (EXACT matches) ====
exact_replacements = [
    ('print(f"[SECURITY] Prompt Injection 拦截: pattern={pattern.pattern[:40]} query={query[:80]}", flush=True)',
     'server_logger.warning(f"Prompt Injection 拦截: pattern={pattern.pattern[:40]} query={query[:80]}")'),
    ('print(f"[KB] 初始化知识库实例: {name} workspace={target}", flush=True)',
     'server_logger.info(f"[KB] 初始化知识库实例: {name} workspace={target}")'),
    ('print(f"[STARTUP-FIX] 修复了 {stuck_count} 个卡在 handling 的文档", flush=True)',
     'server_logger.info(f"[STARTUP-FIX] 修复了 {stuck_count} 个卡在 handling 的文档")'),
    ('print(f"✅ RAG-Anything 服务器已启动，智能体: {len(mgr.agents)}个, 知识库: {list(meta.keys())}")',
     'server_logger.info(f"RAG-Anything 服务器已启动，智能体: {len(mgr.agents)}个, 知识库: {list(meta.keys())}")'),
    ('print(f"[FIX-STUCK] 修复卡住的文档: {filename} (KB={kb_name}) handling→failed", flush=True)',
     'server_logger.warning(f"[FIX-STUCK] 修复卡住的文档: {filename} (KB={kb_name}) handling→failed")'),
    ('print(f"[FIX-STUCK] 修复失败: {ex}", flush=True)',
     'server_logger.error(f"[FIX-STUCK] 修复失败: {ex}")'),
    ('print(f"[UPLOAD] 任务={task_id} 文件={filename} KB={kb_name} 策略={actual_strategy}", flush=True)',
     'server_logger.info(f"[UPLOAD] 任务={task_id} 文件={filename} KB={kb_name} 策略={actual_strategy}")'),
    ('print(f"[WORKER:{task_id}] {text}", flush=True)',
     'server_logger.debug(f"[WORKER:{task_id}] {text}")'),
    ('print(f"[KB] 清除缓存实例: {kb_name}（子进程写入新数据）", flush=True)',
     'server_logger.info(f"[KB] 清除缓存实例: {kb_name}（子进程写入新数据）")'),
]

cnt = 0
for old, new in exact_replacements:
    if old in content:
        content = content.replace(old, new)
        cnt += 1
print(f"6. Print conversions: {cnt} done (some may be in stripped code)")

# ==== 7: Cleanup empty lines and orphan comments ====
content = re.sub(r'\n\n\n+', '\n\n', content)

with open('server.py', 'w', encoding='utf-8') as f:
    f.write(content)

final_lines = content.split('\n')
print(f"Final: {len(final_lines)} lines")
print("DONE")

## 1. Infrastructure Setup — New Module Structure

- [x] 1.1 Create `raganything/services/` directory with `__init__.py` and `__all__` export list
- [x] 1.2 Create `raganything/services/__init__.py` exporting `kb_service`, `ws_service`, `state_service`
- [x] 1.3 Create `raganything/protocols.py` with `RAGCoreProtocol`, `QueryCapable`, `ProcessorCapable`, `BatchCapable` Protocol classes
- [x] 1.4 Create `raganything/utils/` directory, move `utils.py` in, add `security.py` placeholder
- [x] 1.5 Create `raganything/agentic_rag/` directory for agentic_rag sub-package split

## 2. Shared State Consolidation

- [x] 2.1 Extract KB instance management from `routers/shared.py` into `services/kb_service.py` (create_kb, get_kb, delete_kb, list_kbs)
- [x] 2.2 Extract WebSocket management from `routers/shared.py` into `services/ws_service.py` (connect, disconnect, broadcast_progress, broadcast_query_result)
- [x] 2.3 Extract in-memory state tracking from `routers/shared.py` into `services/state_service.py` (query history, processing task status, thread-safe accessors)
- [x] 2.4 Remove duplicate `get_current_user` from `routers/shared.py`; all routers import from `dependencies.py` only
- [x] 2.5 Remove duplicate `Limiter` instance from `routers/shared.py`; all routers use the one from `dependencies.py`
- [x] 2.6 Update `routers/shared.py` to re-export from new service modules for backward compatibility
- [x] 2.7 Update all router modules (`knowledge.py`, `agent.py`, `query.py`, `admin.py`, `auth.py`, `manufacturing.py`) to import from `services/` instead of `shared.py`
- [x] 2.8 Update `server.py` to remove module-level state variables (`kb_instances`, `processing_tasks`), replace with service imports
- [x] 2.9 Run full test suite (`pytest tests/ -x`) to verify no regression

## 3. Root-Level Module Migration

- [x] 3.1 Move `auth.py` logic into `raganything/services/auth.py` preserving all function signatures and behavior
- [x] 3.2 Replace root-level `auth.py` with re-export wrapper: `from raganything.services.auth import *`
- [x] 3.3 Move `agent_manager.py` logic into `raganything/services/agent_manager.py` preserving all function signatures
- [x] 3.4 Replace root-level `agent_manager.py` with re-export wrapper: `from raganything.services.agent_manager import *`
- [x] 3.5 Update `server.py` imports: `from auth` → `from raganything.services.auth`
- [x] 3.6 Update `raganything/dependencies.py` imports from root-level `auth` → `raganything.services.auth`
- [x] 3.7 Update `raganything/routers/shared.py` imports from root-level `auth` → `raganything.services.auth`
- [ ] 3.8 Run full test suite to verify no regression

## 4. Large File Decomposition — modalprocessors.py (1672 lines)

- [x] 4.1 Extract `ImageModalProcessor` class into `raganything/modalprocessors/image.py` (≤400 lines)
- [x] 4.2 Extract `TableModalProcessor` class into `raganything/modalprocessors/table.py` (≤300 lines)
- [x] 4.3 Extract `EquationModalProcessor` class into `raganything/modalprocessors/equation.py` (≤250 lines)
- [x] 4.4 Extract `GenericModalProcessor` class into `raganything/modalprocessors/generic.py` (≤200 lines)
- [x] 4.5 Extract `ContextExtractor` + `ContextConfig` into `raganything/modalprocessors/context.py` (≤400 lines)
- [x] 4.6 Update `raganything/modalprocessors/__init__.py` with explicit exports from all sub-modules
- [x] 4.7 Update all imports across `raganything/` referencing `modalprocessors` to use new sub-module paths
- [ ] 4.8 Run test suite: `pytest tests/test_core_modules.py tests/ -x -k "modal or processor"`

## 5. Large File Decomposition — query/pipeline.py (1445 lines)

- [x] 5.1 Extract streaming methods (`aquery_stream`, `_stream_response`) into `raganything/query/streaming.py` (≤350 lines)
- [x] 5.2 Extract context builder methods (`_retrieve_chunks`, `_build_context`, `_rerank_chunks`) into `raganything/query/context_builder.py` (≤350 lines)
- [x] 5.3 Slim `raganything/query/pipeline.py` to ≤500 lines (core query methods only: `query`, `aquery`, `_execute_llm_query`)
- [x] 5.4 Add call chain annotation comment at top of `query/pipeline.py`
- [x] 5.5 Update `raganything/query/__init__.py` with explicit exports from all sub-modules
- [x] 5.6 Run test suite: `pytest tests/ -x -k "query or conversation"`

## 6. Large File Decomposition — processor/doc_processor.py (1201 lines)

- [x] 6.1 Extract document ingestion methods (`_ingest_document`, `_parse_document`) into `raganything/processor/doc_ingestion.py` (≤400 lines)
- [x] 6.2 Extract document tracking methods (`_track_status`, `_update_progress`, `_handle_failure`) into `raganything/processor/doc_tracking.py` (≤300 lines)
- [x] 6.3 Slim `raganything/processor/doc_processor.py` to ≤500 lines (core orchestration only)
- [x] 6.4 Update `raganything/processor/__init__.py` with explicit exports
- [x] 6.5 Run test suite: `pytest tests/ -x -k "processor or doc"`

## 7. Large File Decomposition — agentic_rag.py (1145 lines)

- [x] 7.1 Extract tool definitions (`_get_tools`, `_register_tool`) into `raganything/agentic_rag/tools.py` (≤400 lines)
- [x] 7.2 Extract ReAct loop logic (`_run_react_loop`, `_execute_action`, `_observe_result`) into `raganything/agentic_rag/react_loop.py` (≤400 lines)
- [x] 7.3 Slim `raganything/agentic_rag/engine.py` to ≤400 lines (AgenticRAG class + initialization + public API)
- [x] 7.4 Create `raganything/agentic_rag/__init__.py` with explicit exports
- [x] 7.5 Update `raganything/raganything.py` import from `agentic_rag` to `agentic_rag.engine`
- [x] 7.6 Run test suite: `pytest tests/ -x -k "agentic"`

## 8. Large File Decomposition — Remaining Files

- [x] 8.1 Split `raganything/chunking.py` (770 lines): extract `recursive.py`, `sentence.py`, `semantic.py`, keep `__init__.py` as registry
- [x] 8.2 Split `raganything/video_processor.py` (942 lines): extract `frame_extractor.py`, `audio_transcriber.py`, `scene_detector.py`
- [x] 8.3 Split `raganything/hybrid_search.py` (556 lines): extract `rrf_fusion.py`, `bm25_search.py`, keep `vector_search.py`
- [x] 8.4 Split `raganything/graph_rag.py` (539 lines): extract `entity_search.py`, `relation_search.py`, `community_search.py`
- [x] 8.5 Split `raganything/utils.py` (618 lines): extract `content_separator.py`, `table_formatter.py`, `sse_helpers.py`, `image_encoder.py`
- [x] 8.6 Run full test suite after each file split to verify no regression

## 9. Layer Boundary Cleanup

- [x] 9.1 Remove `from raganything.parser import get_parser` in `processor/__init__.py`; if needed, add as TODO for caller update
- [x] 9.2 Remove `from raganything.utils import insert_text_content` in `processor/__init__.py`; update callers to import directly
- [x] 9.3 Audit and resolve all imports from `routers/` modules into `raganything/` core (ensure Service layer is used for cross-cutting)
- [x] 9.4 Verify no `raganything/` module imports from root-level files after migration (run grep: `rg "from (auth|agent_manager) import" raganything/`)
- [x] 9.5 Run full test suite

## 10. Vibe Coding Compatibility — Module Headers & Protocols

- [x] 10.1 Add standardized header comments to all 70+ `.py` files: module name, layer, primary responsibility, key dependencies
- [x] 10.2 Add `__all__` export lists to all `__init__.py` files (services, modalprocessors, query, processor, parser, agentic_rag, routers)
- [x] 10.3 Add call chain annotations to `query/pipeline.py`, `processor/doc_processor.py`, `agentic_rag/engine.py`, `workflow_executor.py`
- [x] 10.4 Verify Protocol definitions in `protocols.py` accurately reflect Mixin attribute contracts
- [x] 10.5 Add missing type annotations to public methods across all service and core modules
- [x] 10.6 Run `mypy` or `pyright` on `raganything/` to verify type annotation consistency (warnings acceptable, errors fixed)

## 11. Cleanup & Final Verification

- [x] 11.1 Delete `raganything/parser.py.bak`, `raganything/processor.py.bak`, `raganything/query.py.bak`
- [x] 11.2 Remove `server.py` alias re-import block (lines 160-194), update all references to use direct service imports
- [x] 11.3 Verify no stale imports remain: `rg "from raganything\.(parser|processor|query) import" raganything/` with no `.bak` references
- [x] 11.4 Run full test suite: `pytest tests/ -v` — all 29 test files must pass
- [x] 11.5 Start server and verify all API endpoints respond correctly: `python server.py` smoke test
- [ ] 11.6 Verify frontend integration: confirm all API endpoints used by React SPA return expected response shapes (requires running server with API keys)

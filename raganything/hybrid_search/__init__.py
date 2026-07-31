"""
RRF Hybrid Search Engine — Three-channel parallel retrieval with RRF fusion.

Channels:
  1. BM25 keyword search (Okapi BM25 + jieba tokenizer)
  2. Vector semantic search (via LightRAG's HNSW index)
  3. Knowledge graph search (entity matching + neighbor traversal)

Fusion: RRF (Reciprocal Rank Fusion) — Σ 1/(k + rank_i)
"""

import os
import asyncio
import concurrent.futures
import hashlib
import json
import time
from collections import OrderedDict
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field

from lightrag.utils import logger as lightrag_logger
from raganything.graph_rag import GraphRetriever  # extracted module

# ── Shared ThreadPoolExecutor ────────────────────────────────
# Single shared executor avoids the overhead of creating a new
# ThreadPoolExecutor on every BM25 search call.  Under concurrent
# load this prevents thread-leak storms.
_MAX_BM25_WORKERS = int(os.getenv("BM25_THREAD_WORKERS", "4"))
_RRF_DEADLINE_SETTLE_SECONDS = 0.05
_bm25_executor: concurrent.futures.ThreadPoolExecutor | None = None
_bm25_build_tasks: dict["BM25IndexKey", asyncio.Task["BM25IndexManager"]] = {}


def _get_bm25_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Return the shared BM25 ThreadPoolExecutor, creating it lazily."""
    global _bm25_executor
    if _bm25_executor is None:
        _bm25_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=_MAX_BM25_WORKERS,
            thread_name_prefix="bm25-",
        )
    return _bm25_executor


def _consume_detached_task_result(task: asyncio.Task) -> None:
    """Consume a late channel result so detached timeouts stay warning-free."""
    if task.cancelled():
        return
    try:
        task.exception()
    except asyncio.CancelledError:
        pass


async def _run_channel_with_hard_timeout(coro, timeout: float):
    """Return or fail at the deadline without waiting for cancellation.

    ``asyncio.wait_for`` waits for a cancelled coroutine to finish cleanup.
    Some provider worker pools do not acknowledge cancellation until their own
    health timeout, which used to stall every RRF channel behind one embedding
    request. The late task is cancelled and observed, but no longer blocks the
    usable BM25 or graph results.
    """
    if timeout <= 0:
        coro.close()
        raise TimeoutError("retrieval channel deadline expired")
    task = asyncio.create_task(coro)
    try:
        done, _ = await asyncio.wait({task}, timeout=float(timeout))
    except asyncio.CancelledError:
        task.cancel()
        task.add_done_callback(_consume_detached_task_result)
        raise
    if task not in done:
        task.cancel()
        task.add_done_callback(_consume_detached_task_result)
        raise TimeoutError(f"retrieval channel exceeded {timeout:g}s")
    return task.result()


# ═══════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════


@dataclass
class ScoredChunk:
    """A retrieved chunk with its RRF fusion score and source channels."""

    chunk_id: str
    content: str
    score: float
    sources: List[str] = field(default_factory=list)
    # Per-channel ranks for diagnostics
    bm25_rank: Optional[int] = None
    vector_rank: Optional[int] = None
    graph_rank: Optional[int] = None
    # Source entity names from graph traversal (for entity disambiguation)
    graph_entities: List[str] = field(default_factory=list)
    # Source document tracing fields (for citation display)
    file_path: Optional[str] = None
    document_name: Optional[str] = None
    chunk_index: Optional[int] = None

    def __repr__(self):
        doc = f" doc={self.document_name}" if self.document_name else ""
        return (
            f"ScoredChunk(id={self.chunk_id[:16]}..., score={self.score:.4f}, "
            f"sources={self.sources}{doc})"
        )


@dataclass(frozen=True)
class RetrievalOptions:
    """Immutable request-scoped overrides for hybrid retrieval.

    The engine itself remains reusable, but individual requests must never
    alter its configured channel list or ranking knobs.  ``None`` fields
    inherit the engine defaults for backwards compatibility.
    """

    channels: tuple[str, ...] | None = None
    bm25_top_k: int | None = None
    vector_top_k: int | None = None
    graph_top_k: int | None = None
    graph_depth: int | None = None
    channel_timeout: float | None = None
    rrf_k: int | None = None
    bm25_tokenizer: str | None = None
    bm25_k1: float | None = None
    bm25_b: float | None = None
    # These values are deliberately inputs, never mutable engine state.  The
    # BM25 cache uses workspace/content/configuration identity; callers can
    # carry the additional fields into query/LLM cache scopes.
    workspace: str | None = None
    corpus_revision: str | None = None
    permission_scope: str | None = None
    settings_fingerprint: str | None = None
    # Internal execution deadline; never populated from the settings API.
    deadline_monotonic: float | None = None
    # Trace IDs are log fields only. They are never promoted to metric labels.
    trace_id: str | None = None


@dataclass(frozen=True)
class BM25IndexKey:
    """Identity of a read-only derived BM25 index."""

    workspace: str
    corpus_revision: str
    tokenizer: str
    k1: float
    b: float


class BoundedBM25IndexCache:
    """Small LRU of independent BM25 indexes.

    Entries never overwrite a different workspace, corpus revision, or BM25
    configuration.  Eviction drops only the derived index that lost the LRU
    race; it does not mutate another request's manager.
    """

    def __init__(self, max_size: int = 32):
        self.max_size = max(1, max_size)
        self._store: OrderedDict[BM25IndexKey, "BM25IndexManager"] = OrderedDict()

    def get(self, key: BM25IndexKey) -> "BM25IndexManager | None":
        manager = self._store.get(key)
        if manager is not None:
            self._store.move_to_end(key)
        return manager

    def put(self, key: BM25IndexKey, manager: "BM25IndexManager") -> None:
        self._store[key] = manager
        self._store.move_to_end(key)
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)

    def resize(self, max_size: int) -> None:
        self.max_size = max(1, int(max_size))
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)

    def __len__(self) -> int:
        return len(self._store)


_bm25_index_cache = BoundedBM25IndexCache(
    int(os.getenv("BM25_INDEX_CACHE_CAPACITY", "32"))
)


# ═══════════════════════════════════════════════════════════
# BM25 Keyword Index Manager
# ═══════════════════════════════════════════════════════════


class BM25IndexManager:
    """
    Okapi BM25 inverted index with jieba tokenization.

    Env vars:
        BM25_K1: k1 parameter (default 1.5)
        BM25_B:  b parameter (default 0.75)
        BM25_TOP_K: candidates returned per query (default 50)
        BM25_TOKENIZER: tokenizer choice — "jieba" (default) or "nltk"
    """

    def __init__(
        self,
        tokenizer: Optional[Callable] = None,
        *,
        tokenizer_name: str | None = None,
        k1: float | None = None,
        b: float | None = None,
        top_k: int | None = None,
    ):
        self._k1 = float(os.getenv("BM25_K1", "1.5") if k1 is None else k1)
        self._b = float(os.getenv("BM25_B", "0.75") if b is None else b)
        self._top_k = int(os.getenv("BM25_TOP_K", "50") if top_k is None else top_k)
        self._tokenizer_name = tokenizer_name or os.getenv("BM25_TOKENIZER", "jieba")

        self._index = None
        self._chunks: List[Dict[str, Any]] = []  # [{chunk_id, content}, ...]
        self._tokenizer = tokenizer or self._create_tokenizer()
        self._lock = asyncio.Lock()  # guards index rebuilds

    # ------------------------------------------------------------------
    # Tokenizer
    # ------------------------------------------------------------------

    def _create_tokenizer(self) -> Callable[[str], List[str]]:
        """Create the configured tokenizer function."""
        if self._tokenizer_name == "nltk":
            try:
                import nltk

                nltk.download("punkt", quiet=True)
                return lambda text: nltk.word_tokenize(text.lower())
            except ImportError:
                lightrag_logger.warning(
                    "NLTK not installed for BM25 tokenizer; falling back to jieba"
                )

        # Default: jieba
        import jieba

        return lambda text: list(jieba.cut(text))

    # ------------------------------------------------------------------
    # Index Building
    # ------------------------------------------------------------------

    def build_index(self, chunks: List[Dict[str, Any]]):
        """Build BM25 index from a list of chunks (synchronous blocking call).

        Args:
            chunks: List of {'chunk_id': str, 'content': str}
        """
        from rank_bm25 import BM25Okapi

        self._chunks = list(chunks)
        if not self._chunks:
            self._index = None
            return

        corpus = [self._tokenizer(c["content"]) for c in self._chunks]
        self._index = BM25Okapi(
            corpus, k1=self._k1, b=self._b, epsilon=0.25
        )

    async def rebuild_index_async(self, chunks: List[Dict[str, Any]]):
        """Async-safe index rebuild: build in background, atomically swap."""
        loop = asyncio.get_running_loop()
        async with self._lock:
            await loop.run_in_executor(
                _get_bm25_executor(), self.build_index, list(chunks)
            )

    async def update_index_incremental(self, new_chunks: List[Dict[str, Any]]):
        """Rebuild index with added chunks (full rebuild for correctness)."""
        # For BM25Okapi accuracy, we rebuild the entire index.
        # Future optimization: shard-based partial rebuild for large corpora.
        all_chunks = self._chunks + list(new_chunks)
        await self.rebuild_index_async(all_chunks)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self, query: str, top_k: int | None = None
    ) -> List[ScoredChunk]:
        """Search BM25 index, returning scored results.

        Args:
            query: Search query string
            top_k: Max results (default: BM25_TOP_K env var)

        Returns:
            List of ScoredChunk with bm25 sources, ranked by BM25 score descending
        """
        top_k = top_k or self._top_k
        if self._index is None or not self._chunks:
            return []

        tokenized = self._tokenizer(query)
        if not tokenized:
            return []

        scores = self._index.get_scores(tokenized)
        # Get top_k indices sorted by score descending
        if len(scores) <= top_k:
            ranked_indices = sorted(
                range(len(scores)), key=lambda i: scores[i], reverse=True
            )
        else:
            # Use argpartition for efficiency with large result sets
            import numpy as np

            ranked_indices = np.argsort(scores)[::-1][:top_k].tolist()

        results = []
        for rank, idx in enumerate(ranked_indices):
            chunk = self._chunks[idx]
            results.append(
                ScoredChunk(
                    chunk_id=chunk["chunk_id"],
                    content=chunk["content"],
                    score=float(scores[idx]),
                    sources=["bm25"],
                    bm25_rank=rank + 1,
                )
            )
        return results

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def is_ready(self) -> bool:
        return self._index is not None

    @property
    def cache_parameters(self) -> tuple[str, float, float]:
        return (self._tokenizer_name, self._k1, self._b)

# ═══════════════════════════════════════════════════════════


class HybridSearchEngine:
    """
    Three-channel parallel retrieval with RRF fusion.

    Channels:
      - BM25 keyword search (Okapi BM25)
      - Vector semantic search (LightRAG HNSW)
      - Knowledge graph search (entity + traversal)

    Env vars:
        RRF_K: RRF constant k (default 60)
        VECTOR_TOP_K: vector channel candidate count (default 100)
        BM25_TOP_K: BM25 channel candidate count (default 50) — read by BM25IndexManager
        GRAPH_TOP_K: graph channel candidate count (default 30) — read by GraphRetriever
        RRF_ENABLED_CHANNELS: comma-separated list, e.g. "bm25,vector,graph"
    """

    def __init__(
        self,
        lightrag_instance=None,
        bm25_manager: Optional[BM25IndexManager] = None,
        graph_retriever: Optional[GraphRetriever] = None,
    ):
        self._lightrag = lightrag_instance
        self._bm25 = bm25_manager or BM25IndexManager()
        self._graph = graph_retriever or GraphRetriever(lightrag_instance)

        self._rrf_k = int(os.getenv("RRF_K", "60"))
        self._vector_top_k = int(os.getenv("VECTOR_TOP_K", "100"))

        # Which channels to enable
        default_channels = "bm25,vector,graph"
        channels_str = os.getenv("RRF_ENABLED_CHANNELS", default_channels)
        self._enabled_channels = [
            c.strip() for c in channels_str.split(",") if c.strip()
        ]

        self._bm25_top_k = int(os.getenv("BM25_TOP_K", "50"))
        self._graph_top_k = int(os.getenv("GRAPH_TOP_K", "30"))

        self._channel_timeout = float(os.getenv("RRF_CHANNEL_TIMEOUT", "10.0"))

        self._logger = lightrag_logger

    def set_lightrag(self, lightrag_instance):
        """Set/update the LightRAG instance reference."""
        self._lightrag = lightrag_instance
        self._graph.set_lightrag(lightrag_instance)

    @property
    def graph_retriever(self) -> GraphRetriever:
        """Public accessor for the graph retrieval channel."""
        return self._graph

    async def _bm25_for_options(
        self, options: RetrievalOptions | None
    ) -> BM25IndexManager:
        """Resolve a read-only BM25 index without mutating shared state."""
        if self._lightrag is None:
            return self._bm25

        timing = None
        if options and options.trace_id:
            from raganything.services.query_timing import QueryTiming

            timing = QueryTiming(options.trace_id)

        async def _observe_bm25_phase(phase: str, cache_status: str, operation):
            """Record PG/index work without carrying query or provider data."""
            started = time.perf_counter()
            outcome = "ok"
            try:
                return await operation()
            except asyncio.CancelledError:
                outcome = "cancelled"
                raise
            except Exception:
                outcome = "error"
                raise
            finally:
                if timing is not None:
                    timing.record(
                        phase,
                        time.perf_counter() - started,
                        outcome=outcome,
                        cache_status=cache_status,
                        channel="bm25",
                    )

        async def _fetch_rows(workspace: str, cache_status: str):
            async def _fetch():
                from raganything.services.pg_state_repo import get_pg_pool

                pool = get_pg_pool()
                async with pool.acquire() as conn:
                    return await conn.fetch(
                        "SELECT chunks_list FROM LIGHTRAG_DOC_STATUS WHERE workspace=$1",
                        workspace,
                    )

            return await _observe_bm25_phase("bm25_pg_read", cache_status, _fetch)

        try:
            workspace = str(self._lightrag.working_dir)
            tokenizer = options.bm25_tokenizer if options and options.bm25_tokenizer else self._bm25._tokenizer_name
            k1 = float(options.bm25_k1) if options and options.bm25_k1 is not None else self._bm25._k1
            b = float(options.bm25_b) if options and options.bm25_b is not None else self._bm25._b
            requested_revision = options.corpus_revision if options and options.corpus_revision else None
            if requested_revision:
                requested_key = BM25IndexKey(
                    workspace=options.workspace if options and options.workspace else workspace,
                    corpus_revision=requested_revision,
                    tokenizer=tokenizer,
                    k1=k1,
                    b=b,
                )
                cached = _bm25_index_cache.get(requested_key)
                if cached is not None:
                    return cached
                build_task = _bm25_build_tasks.get(requested_key)
                if build_task is None:
                    async def _build_requested_index() -> BM25IndexManager:
                        rows = await _fetch_rows(workspace, "miss")
                        chunk_ids: list[str] = []
                        for row in rows:
                            chunk_list = row["chunks_list"]
                            if isinstance(chunk_list, str):
                                try:
                                    chunk_list = json.loads(chunk_list)
                                except (TypeError, ValueError):
                                    chunk_list = []
                            if isinstance(chunk_list, list):
                                chunk_ids.extend(str(value) for value in chunk_list)
                        async def _build():
                            manager = BM25IndexManager(
                                tokenizer_name=tokenizer,
                                k1=k1,
                                b=b,
                                top_k=self._bm25_top_k,
                            )
                            if chunk_ids:
                                raw_chunks = await self._lightrag.text_chunks.get_by_ids(chunk_ids)
                                chunks = [
                                    {
                                        "chunk_id": chunk.get("id") or chunk.get("__id__"),
                                        "content": chunk.get("content", ""),
                                    }
                                    for chunk in raw_chunks
                                    if chunk
                                    and (chunk.get("id") or chunk.get("__id__"))
                                    and chunk.get("content")
                                ]
                                if chunks:
                                    await manager.rebuild_index_async(chunks)
                            _bm25_index_cache.put(requested_key, manager)
                            return manager

                        return await _observe_bm25_phase("bm25_build", "miss", _build)

                    build_task = asyncio.create_task(_build_requested_index())
                    _bm25_build_tasks[requested_key] = build_task

                    def _release_requested_build(done: asyncio.Task) -> None:
                        if _bm25_build_tasks.get(requested_key) is done:
                            _bm25_build_tasks.pop(requested_key, None)
                        if not done.cancelled():
                            try:
                                done.exception()
                            except Exception:
                                self._logger.warning("Scoped BM25 build failed", exc_info=True)

                    build_task.add_done_callback(_release_requested_build)
                from raganything.services.query_execution import await_before_deadline

                return await await_before_deadline(
                    asyncio.shield(build_task),
                    options.deadline_monotonic if options else None,
                    cancel_on_timeout=False,
                )
            rows = await _fetch_rows(workspace, "miss")
            chunk_ids: list[str] = []
            for row in rows:
                chunk_list = row["chunks_list"]
                if isinstance(chunk_list, str):
                    try:
                        chunk_list = json.loads(chunk_list)
                    except (TypeError, ValueError):
                        chunk_list = []
                if isinstance(chunk_list, list):
                    chunk_ids.extend(str(value) for value in chunk_list)
            corpus_revision = hashlib.sha256(
                json.dumps(sorted(chunk_ids), separators=(",", ":")).encode()
            ).hexdigest()[:32]
            key = BM25IndexKey(
                workspace=options.workspace if options and options.workspace else workspace,
                corpus_revision=options.corpus_revision if options and options.corpus_revision else corpus_revision,
                tokenizer=tokenizer,
                k1=k1,
                b=b,
            )
            try:
                from raganything.services.user_settings import get_platform_settings

                platform = await get_platform_settings()
                capacity = ((platform.get("settings") or {}).get("limits") or {}).get(
                    "cache_capacity"
                )
                if isinstance(capacity, int) and capacity > 0:
                    _bm25_index_cache.resize(capacity)
            except Exception:
                pass

            cached = _bm25_index_cache.get(key)
            if cached is not None:
                return cached
            build_task = _bm25_build_tasks.get(key)
            if build_task is None:
                async def _build_index() -> BM25IndexManager:
                    async def _build():
                        manager = BM25IndexManager(
                            tokenizer_name=tokenizer,
                            k1=k1,
                            b=b,
                            top_k=self._bm25_top_k,
                        )
                        if not chunk_ids:
                            _bm25_index_cache.put(key, manager)
                            return manager
                        raw_chunks = await self._lightrag.text_chunks.get_by_ids(chunk_ids)
                        chunks = [
                            {
                                "chunk_id": chunk.get("id") or chunk.get("__id__"),
                                "content": chunk.get("content", ""),
                            }
                            for chunk in raw_chunks
                            if chunk
                            and (chunk.get("id") or chunk.get("__id__"))
                            and chunk.get("content")
                        ]
                        if chunks:
                            await manager.rebuild_index_async(chunks)
                        _bm25_index_cache.put(key, manager)
                        return manager

                    return await _observe_bm25_phase("bm25_build", "miss", _build)

                build_task = asyncio.create_task(_build_index())
                _bm25_build_tasks[key] = build_task
            try:
                # Shield ensures one impatient request cannot cancel the
                # single-flight build still needed by another caller.
                from raganything.services.query_execution import await_before_deadline

                return await await_before_deadline(
                    asyncio.shield(build_task),
                    options.deadline_monotonic if options else None,
                    cancel_on_timeout=False,
                )
            finally:
                if build_task.done():
                    _bm25_build_tasks.pop(key, None)
        except Exception as exc:
            self._logger.warning("Failed to resolve scoped BM25 index: %s", exc)
            if options is None:
                return self._bm25
            return BM25IndexManager(
                tokenizer_name=options.bm25_tokenizer or self._bm25._tokenizer_name,
                k1=options.bm25_k1 if options.bm25_k1 is not None else self._bm25._k1,
                b=options.bm25_b if options.bm25_b is not None else self._bm25._b,
                top_k=self._bm25_top_k,
            )

    async def ensure_bm25_index(self):
        """Build BM25 index from existing LightRAG chunks if not already built.

        Called after initialization to ensure the BM25 index covers all
        existing documents in the knowledge base.
        """
        if self._bm25.is_ready:
            return

        if self._lightrag is None:
            self._logger.warning("No LightRAG instance, skipping BM25 index build")
            return

        try:
            import json as _json

            # ── PG-only: read chunk IDs from doc_status, fetch via LightRAG KV ──
            from raganything.services.pg_state_repo import get_pg_pool
            workspace = str(self._lightrag.working_dir)
            pool = get_pg_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT chunks_list FROM LIGHTRAG_DOC_STATUS WHERE workspace=$1",
                    workspace,
                )
            all_chunk_ids: list[str] = []
            for row in rows:
                chunks_list = row["chunks_list"]
                if isinstance(chunks_list, str):
                    try:
                        chunks_list = _json.loads(chunks_list)
                    except Exception:
                        chunks_list = []
                if chunks_list:
                    all_chunk_ids.extend(chunks_list)

            if not all_chunk_ids:
                self._logger.info("No chunks found in PG doc_status for BM25 index build")
                return

            # Fetch chunks from LightRAG's text_chunks KV storage (PG-backed)
            raw_chunks = await self._lightrag.text_chunks.get_by_ids(all_chunk_ids)
            chunk_list = []
            for chunk in raw_chunks:
                if chunk:
                    cid = chunk.get("id") or chunk.get("__id__")
                    content = chunk.get("content", "")
                    if cid and content:
                        chunk_list.append({"chunk_id": cid, "content": content})

            if chunk_list:
                await self._bm25.rebuild_index_async(chunk_list)
                self._logger.info(f"BM25 index built from {len(chunk_list)} PG chunks")
        except Exception as exc:
            self._logger.warning(f"Failed to build BM25 index from PG chunks: {exc}")

    # ------------------------------------------------------------------
    # Channel Searches
    # ------------------------------------------------------------------

    async def _bm25_search(
        self, manager: BM25IndexManager, query: str, top_k: int
    ) -> List[ScoredChunk]:
        """BM25 channel (sync, run in shared executor)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _get_bm25_executor(), manager.search, query, top_k
        )

    async def _vector_search(self, query: str, top_k: int) -> List[ScoredChunk]:
        """Vector semantic search via LightRAG's internal retrieval."""
        if self._lightrag is None:
            return []

        try:
            # Use LightRAG's query with only_need_context to get raw chunks
            from lightrag import QueryParam

            param = QueryParam(mode="naive", only_need_context=True, top_k=top_k)
            result = await self._lightrag.aquery(query, param=param)

            if not result or not isinstance(result, str):
                return []

            # LightRAG returns context as a formatted string; extract chunk references
            chunks = self._parse_lightrag_context(result)
            return [
                ScoredChunk(
                    chunk_id=c.get("chunk_id", str(i)),
                    content=c.get("content", ""),
                    score=1.0,  # Will be replaced by RRF rank
                    sources=["vector"],
                    vector_rank=i + 1,
                )
                for i, c in enumerate(chunks[:top_k])
            ]
        except Exception as exc:
            self._logger.warning(f"Vector search failed: {exc}")
            return []

    async def _graph_search(
        self, query: str, top_k: int, graph_depth: int | None = None
    ) -> List[ScoredChunk]:
        """Knowledge graph search (async)."""
        return await self._graph.search(query, top_k, depth=graph_depth)

    # ------------------------------------------------------------------
    # RRF Fusion
    # ------------------------------------------------------------------

    @staticmethod
    def _rrf_fuse(
        channel_results: List[List[ScoredChunk]], k: int = 60
    ) -> List[ScoredChunk]:
        """RRF fusion: Σ 1/(k + rank_i) for each chunk across channels.

        Args:
            channel_results: Per-channel result lists (ordered by channel rank)
            k: RRF constant (default 60)

        Returns:
            Fused results sorted by RRF score descending, with dedup and source labels
        """
        # Aggregate: {chunk_id: {score, content, sources, ranks}}
        fused: Dict[str, Dict[str, Any]] = {}

        channel_names = ["bm25", "vector", "graph"]
        for ch_idx, results in enumerate(channel_results):
            for rank, chunk in enumerate(results):
                cid = chunk.chunk_id
                rrf_contrib = 1.0 / (k + rank + 1)

                if cid not in fused:
                    fused[cid] = {
                        "chunk_id": cid,
                        "content": chunk.content,
                        "score": 0.0,
                        "sources": [],
                        "bm25_rank": None,
                        "vector_rank": None,
                        "graph_rank": None,
                    }

                entry = fused[cid]
                entry["score"] += rrf_contrib
                ch_name = channel_names[ch_idx] if ch_idx < len(channel_names) else f"ch{ch_idx}"
                if ch_name not in entry["sources"]:
                    entry["sources"].append(ch_name)
                # Preserve best per-channel rank
                rank_key = f"{ch_name}_rank"
                current = entry.get(rank_key)
                if current is None or (rank + 1) < current:
                    entry[rank_key] = rank + 1

        # Build result list
        result_list = [
            ScoredChunk(
                chunk_id=v["chunk_id"],
                content=v["content"],
                score=v["score"],
                sources=v["sources"],
                bm25_rank=v.get("bm25_rank"),
                vector_rank=v.get("vector_rank"),
                graph_rank=v.get("graph_rank"),
            )
            for v in fused.values()
        ]

        result_list.sort(key=lambda c: c.score, reverse=True)
        return result_list

    # ------------------------------------------------------------------
    # Main Search Entry Point
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        top_k: int = 100,
        channels: List[str] | None = None,
        options: RetrievalOptions | None = None,
    ) -> List[ScoredChunk]:
        """Main RRF hybrid search: parallel channels → fuse → return.

        Args:
            query: Search query
            top_k: Final number of results after fusion
            channels: Deprecated per-call channel override (e.g. ["bm25", "vector"])
            options: Immutable request-scoped retrieval configuration.

        Returns:
            Fused, deduplicated, RRF-scored results
        """
        enabled_channels = (
            list(options.channels)
            if options is not None and options.channels is not None
            else list(channels) if channels is not None else list(self._enabled_channels)
        )
        bm25_top_k = options.bm25_top_k if options and options.bm25_top_k is not None else self._bm25_top_k
        vector_top_k = options.vector_top_k if options and options.vector_top_k is not None else self._vector_top_k
        graph_top_k = options.graph_top_k if options and options.graph_top_k is not None else self._graph_top_k
        graph_depth = options.graph_depth if options and options.graph_depth is not None else None
        channel_timeout = options.channel_timeout if options and options.channel_timeout is not None else self._channel_timeout
        rrf_k = options.rrf_k if options and options.rrf_k is not None else self._rrf_k
        deadline = options.deadline_monotonic if options else None
        timing = None
        if options and options.trace_id:
            from raganything.services.query_timing import QueryTiming
            timing = QueryTiming(options.trace_id)

        def effective_timeout() -> float | None:
            if deadline is None:
                return channel_timeout
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return None
            # Leave a bounded scheduling window for channel cancellation,
            # gather(), and fusion to return before the request-wide deadline.
            # Without this, a channel that times out exactly at the deadline can
            # race the router's watchdog and turn a recoverable RRF fallback
            # into an SSE error.
            settle_window = min(_RRF_DEADLINE_SETTLE_SECONDS, max(0.0, remaining / 2))
            return min(channel_timeout, remaining - settle_window)

        async def timed_channel(label: str, coro) -> List[ScoredChunk]:
            started = asyncio.get_running_loop().time()
            try:
                timeout = effective_timeout()
                if timeout is None:
                    coro.close()
                    raise TimeoutError("retrieval channel deadline expired")
                result = await _run_channel_with_hard_timeout(coro, timeout)
            except TimeoutError:
                if timing is not None:
                    timing.record(
                        "retrieval",
                        asyncio.get_running_loop().time() - started,
                        outcome="timeout",
                        channel=label,
                    )
                raise
            except Exception:
                if timing is not None:
                    timing.record(
                        "retrieval",
                        asyncio.get_running_loop().time() - started,
                        outcome="error",
                        channel=label,
                    )
                raise
            if timing is not None:
                timing.record(
                    "retrieval",
                    asyncio.get_running_loop().time() - started,
                    channel=label,
                )
            return result

        # Launch all enabled channels in parallel with per-channel timeout
        tasks = []
        task_labels = []

        if "bm25" in enabled_channels:
            async def _bm25_channel():
                manager = await self._bm25_for_options(options)
                return await self._bm25_search(manager or self._bm25, query, bm25_top_k)

            tasks.append(
                timed_channel("bm25", _bm25_channel())
            )
            task_labels.append("bm25")

        if "vector" in enabled_channels:
            tasks.append(
                timed_channel("vector", self._vector_search(query, vector_top_k))
            )
            task_labels.append("vector")

        if "graph" in enabled_channels:
            tasks.append(
                timed_channel("graph", self._graph_search(query, graph_top_k, graph_depth))
            )
            task_labels.append("graph")

        if not tasks:
            return []

        # Run in parallel, catching per-channel failures
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        channel_results: List[List[ScoredChunk]] = []
        for label, result in zip(task_labels, gathered):
            if isinstance(result, Exception):
                self._logger.warning(
                    f"Channel '{label}' failed or timed out: {result}"
                )
                channel_results.append([])
            elif isinstance(result, list):
                channel_results.append(result)
            else:
                channel_results.append([])

        # Check if ALL channels failed
        if all(len(r) == 0 for r in channel_results):
            self._logger.error("All RRF channels failed — returning empty results")
            return []

        # RRF fusion
        fused = self._rrf_fuse(channel_results, k=rrf_k)
        return fused[:top_k]

    # ------------------------------------------------------------------
    # Context Parsing Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_lightrag_context(raw_context: str) -> List[Dict[str, Any]]:
        """Parse LightRAG's only_need_context output into structured chunk list.

        LightRAG returns context as chunks separated by double newlines, each
        prefixed with a chunk_id marker like ``[chunk_xxx]`` or ``{chunk_id}``.
        """
        if not raw_context:
            return []

        import re

        # Reject LightRAG's fail_response — it contains the "[no-context]" sentinel
        # and is NOT a real document chunk. Without this guard, the fail_response
        # text "Sorry, I'm not able to provide an answer..." would be parsed as a
        # fake chunk and fed into RRF fusion, producing garbage results.
        if "[no-context]" in raw_context:
            return []

        chunks = []
        # Split on common chunk separators
        parts = re.split(r"\n(?=\[|\{)", raw_context)
        if len(parts) <= 1:
            parts = raw_context.split("\n\n")

        for part in parts:
            part = part.strip()
            if not part:
                continue
            # Try to extract chunk_id marker
            marker_match = re.match(r"[\[{]([^\]}]+)[\]}]", part)
            chunk_id = marker_match.group(1) if marker_match else ""
            content = part[marker_match.end():].strip() if marker_match else part
            if content:
                chunks.append({"chunk_id": chunk_id, "content": content[:500]})

        return chunks

    # ------------------------------------------------------------------
    # Index Management Delegates
    # ------------------------------------------------------------------

    async def build_bm25_index(self, chunks: List[Dict[str, Any]]):
        """Build/rebuild BM25 index from chunks."""
        await self._bm25.rebuild_index_async(chunks)

    async def update_bm25_index(self, new_chunks: List[Dict[str, Any]]):
        """Incrementally update BM25 index with new chunks."""
        await self._bm25.update_index_incremental(new_chunks)

    @property
    def bm25_ready(self) -> bool:
        return self._bm25.is_ready

    # ------------------------------------------------------------------
    # Graph Visualization Delegate
    # ------------------------------------------------------------------

    async def get_subgraph(
        self, entity_ids: List[str] | None = None, query: str | None = None
    ) -> Dict[str, Any]:
        """Get subgraph data for visualization."""
        return await self._graph.get_subgraph(entity_ids=entity_ids, query=query)

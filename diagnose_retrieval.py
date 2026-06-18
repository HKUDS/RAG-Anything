# -*- coding: utf-8 -*-
"""Diagnostic script v3: Full retrieval path test - no emoji"""
import os
import sys
import json
import asyncio
import time

# Force UTF-8 output on Windows
sys.stdout.reconfigure(encoding='utf-8')

os.chdir(r'c:\Users\98014\RAG-Anything')

from dotenv import load_dotenv
load_dotenv()

from functools import partial
from lightrag.kg.shared_storage import set_default_workspace
from lightrag.utils import EmbeddingFunc
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from raganything import RAGAnything, RAGAnythingConfig

API_KEY = os.getenv("LLM_BINDING_API_KEY")
BASE_URL = os.getenv("LLM_BINDING_HOST")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-max")
EMB_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
EMB_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))

print("=" * 60)
print("KB Retrieval Alignment Diagnostic v3")
print("API KEY: %s..." % API_KEY[:8])
print("LLM: %s | EMB: %s (dim=%d)" % (LLM_MODEL, EMB_MODEL, EMB_DIM))
print("=" * 60)

# Step 1: Verify data on disk
print("\n[1] Disk Data Verification")
for fname, label in [
    ('vdb_chunks.json', 'Vector Chunks'),
    ('kv_store_text_chunks.json', 'Text Chunks'),
    ('kv_store_full_docs.json', 'Full Docs'),
    ('kv_store_doc_status.json', 'Doc Status'),
    ('graph_chunk_entity_relation.graphml', 'Knowledge Graph'),
]:
    path = 'rag_storage_111/%s' % fname
    if not os.path.exists(path):
        print("  [%s] MISSING [FAIL]" % label)
        continue
    size_kb = os.path.getsize(path) / 1024
    if fname.endswith('.graphml'):
        print("  [%s] %.0fKB OK" % (label, size_kb))
        continue
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict) and 'data' in data:
        count = len(data['data'])
        dim = data.get('embedding_dim', '?')
        print("  [%s] %d items, dim=%s, %.0fKB OK" % (label, count, dim, size_kb))
    else:
        print("  [%s] %d entries, %.0fKB OK" % (label, len(data), size_kb))

# Step 2: Create RAGAnything instance
print("\n[2] Initialize RAGAnything (get_kb flow)")
set_default_workspace("./rag_storage_111")

llm_func = lambda prompt, system_prompt=None, history_messages=[], **kw: \
    openai_complete_if_cache(LLM_MODEL, prompt, system_prompt=system_prompt,
        history_messages=history_messages, api_key=API_KEY, base_url=BASE_URL, **kw)

embedding_func = EmbeddingFunc(
    embedding_dim=EMB_DIM, max_token_size=8192,
    func=partial(openai_embed.func, model=EMB_MODEL, api_key=API_KEY, base_url=BASE_URL),
)

config = RAGAnythingConfig(working_dir="./rag_storage_111", parser="mineru")
rag = RAGAnything(config=config, llm_model_func=llm_func, embedding_func=embedding_func)

async def diagnose():
    t0 = time.time()
    result = await rag._ensure_lightrag_initialized()
    t1 = time.time()
    print("  LightRAG init: %s (%.1fs)" % (result.get('success', '?'), t1 - t0))

    if not result.get('success'):
        print("  ERROR: %s" % result)
        return

    # Check hybrid search engine
    hse = rag.hybrid_search_engine
    has_hse = hse is not None
    print("  HybridSearchEngine: %s" % ("INITIALIZED" if has_hse else "NULL [FAIL]"))

    if hse:
        # BM25 index
        bm25_count = 0
        if hasattr(hse, 'bm25_index') and hse.bm25_index:
            bm25_count = len(hse.bm25_index.doc_freqs) if hasattr(hse.bm25_index, 'doc_freqs') else 0
        print("  BM25 Index: %d tokens" % bm25_count)

        # Vector DB
        if rag.lightrag and hasattr(rag.lightrag, 'chunks_vdb'):
            chunks_vdb = rag.lightrag.chunks_vdb
            count = len(chunks_vdb._data) if hasattr(chunks_vdb, '_data') else '?'
            print("  Vector Index: %s items" % count)

        # KV stores
        if rag.lightrag:
            stores_status = rag.lightrag._storages_status
            print("  Storage Status: %s" % stores_status)

    # Step 3: RRF search test
    print("\n[3] RRF Search Test")
    query = "MobileNetV3 system functions and modules"
    print("  Query: %s" % query)

    if not hse:
        print("  [SKIP] No HybridSearchEngine")
        return

    # Full RRF search
    chunks = await hse.search(query, top_k=20)
    t2 = time.time()
    print("  RRF Results: %d chunks (%.1fs)" % (len(chunks), t2 - t1))

    if chunks:
        for i, ch in enumerate(chunks[:5]):
            score = ch.score if hasattr(ch, 'score') else 0
            src = ch.sources[:2] if hasattr(ch, 'sources') else []
            clen = len(ch.content) if hasattr(ch, 'content') else 0
            print("    [%d] score=%.3f src=%s content_len=%d" % (i+1, score, src, clen))
    else:
        print("    [FAIL] 0 results - testing individual channels...")

        # Channel 1: Vector search
        print("\n  Channel 1: Vector Search")
        if rag.lightrag and hasattr(rag.lightrag, 'chunks_vdb'):
            try:
                query_emb = embedding_func.func([query])
                results = rag.lightrag.chunks_vdb.query(query_emb[0], top_k=10)
                print("    Results: %d" % (len(results) if results else 0))
                if results:
                    for r in results[:3]:
                        rid = r.get('__id__', '?') if isinstance(r, dict) else str(r)[:80]
                        print("      id=%s" % rid)
            except Exception as e:
                print("    ERROR: %s" % e)

        # Channel 2: BM25 search
        print("\n  Channel 2: BM25 Search")
        if hasattr(hse, 'bm25_index') and hse.bm25_index:
            try:
                bm25_results = hse.bm25_index.search(query, top_k=10)
                print("    Results: %d" % (len(bm25_results) if bm25_results else 0))
                if bm25_results:
                    for br in bm25_results[:3]:
                        print("      %s" % str(br)[:150])
            except Exception as e:
                print("    ERROR: %s" % e)

        # Channel 3: Graph entity check
        print("\n  Channel 3: Graph Entities")
        if rag.lightrag:
            try:
                from lightrag.kg.shared_storage import get_namespace_data
                ents = get_namespace_data("full_entities")
                if ents:
                    print("    Total entities: %d" % len(ents))
                    # Show some entity names
                    keys = list(ents.keys())[:5]
                    for k in keys:
                        print("      %s" % k[:80])
            except Exception as e:
                print("    ERROR: %s" % e)

    # Step 4: Full aquery flow
    print("\n[4] Full aquery() Flow")
    try:
        ctx = await rag.aquery(query, mode="rrf", only_need_context=True, top_k=10)
        t3 = time.time()
        if isinstance(ctx, str):
            print("  Return: %d chars (%.1fs)" % (len(ctx), t3 - t1))
            # Show first 300 chars
            preview = ctx[:300].replace('\n', '\\n')
            print("  Content: %s" % preview)
        else:
            print("  Return type: %s" % type(ctx).__name__)
    except Exception as e:
        print("  ERROR: %s" % e)
        import traceback
        traceback.print_exc()

    # Cleanup
    if rag.lightrag:
        await rag.lightrag.finalize_storages()
    print("\nDiagnostic complete.")

asyncio.run(diagnose())

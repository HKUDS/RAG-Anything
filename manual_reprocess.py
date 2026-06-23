"""Manual reprocess script to diagnose image chunk creation issues."""
import asyncio, json, os, sys, time
from pathlib import Path

# UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

# Add project root
sys.path.insert(0, '.')

from dotenv import load_dotenv
load_dotenv(override=True)

async def main():
    from raganything.services.kb_service import get_kb
    from raganything.utils._content import separate_content
    from raganything.services.ws_service import ws_broadcast, add_event
    from raganything.services.kb_service import kb_dir
    from lightrag.utils import logger as kb_logger

    kb_name = "test"
    print(f"=== Manual reprocess for KB: {kb_name} ===\n")

    # 1. Get KB instance
    print("[1] Getting KB instance...")
    instance = await get_kb(kb_name)
    if instance is None or instance.lightrag is None:
        print(f"ERROR: KB '{kb_name}' not initialized")
        return

    active_processors = [
        k for k, v in (instance.modal_processors or {}).items() if v is not None
    ]
    print(f"  Active processors: {active_processors}")

    # 2. Scan doc_status
    print("\n[2] Scanning doc_status...")
    status_path = Path(kb_dir(kb_name)) / "kv_store_doc_status.json"
    if not status_path.exists():
        print("ERROR: No doc_status file")
        return

    with open(status_path, "r", encoding="utf-8") as f:
        all_docs = json.load(f)

    needs_processing = []
    for doc_id, info in all_docs.items():
        if info.get("status") == "failed":
            continue
        if not info.get("multimodal_processed", False):
            needs_processing.append((doc_id, dict(info)))

    print(f"  Documents needing processing: {len(needs_processing)}")
    if not needs_processing:
        print("  All docs already processed!")
        return

    # 3. Process first doc
    doc_id, info = needs_processing[0]
    file_ref = info.get("file_path", "")
    print(f"\n[3] Processing doc: {doc_id[:50]}...")
    print(f"  file_ref: {file_ref}")

    # 4. Read parse cache
    print("\n[4] Reading parse cache...")
    kb_workspace = Path(kb_dir(kb_name))
    cache_file = kb_workspace / "kv_store_parse_cache.json"
    content_list = None

    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            all_cache = json.load(f)
        print(f"  Cache entries: {len(all_cache)}")
        for entry in all_cache.values():
            if isinstance(entry, dict) and entry.get("doc_id") == doc_id:
                content_list = entry.get("content_list")
                print(f"  Found matching cache entry, content_list items: {len(content_list)}")
                break

    if content_list is None:
        print("  ERROR: No cache entry found for this doc!")
        return

    # 5. Separate multimodal content
    print("\n[5] Separating multimodal content...")
    _, multimodal_items = separate_content(content_list)
    print(f"  Multimodal items: {len(multimodal_items)}")

    # Count types
    types = {}
    for item in multimodal_items:
        t = item.get("type", "unknown")
        types[t] = types.get(t, 0) + 1
    print(f"  Types: {types}")

    # Check image items for img_path
    img_count = 0
    has_path = 0
    for item in multimodal_items:
        if item.get("type") == "image":
            img_count += 1
            if item.get("img_path"):
                has_path += 1
    print(f"  Images: {img_count}, with img_path: {has_path}")

    if not multimodal_items:
        print("  No multimodal content to process!")
        return

    # 6. Process multimodal content
    print(f"\n[6] Processing {len(multimodal_items)} multimodal items...")
    print("  This will take several minutes (VLM analysis per image)...")
    t0 = time.time()

    try:
        await instance._process_multimodal_content(
            multimodal_items, str(Path("uploads") / Path(file_ref).name), doc_id
        )
        elapsed = time.time() - t0
        print(f"\n  Processing complete! Took {elapsed:.1f}s")

        # Check result
        with open(Path(kb_dir(kb_name)) / "kv_store_text_chunks.json", "r", encoding="utf-8") as f:
            chunks = json.load(f)
        img_chunks = sum(1 for c in chunks.values() if 'Image Path:' in (c.get('content','') if isinstance(c,dict) else str(c)))
        print(f"  Text chunks now: {len(chunks)}, with Image Path: {img_chunks}")

        # Check doc status
        with open(status_path, "r", encoding="utf-8") as f:
            status = json.load(f)
        for did, info in status.items():
            if did == doc_id:
                print(f"  multimodal_processed: {info.get('multimodal_processed', 'KEY_MISSING')}")
                print(f"  chunks_count: {info.get('chunks_count', '?')}")

    except Exception as e:
        import traceback
        print(f"\n  ERROR: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

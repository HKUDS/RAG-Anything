"""Document indexes for LightRAG merges that run after text ingestion."""

from lightrag.kg.shared_storage import get_storage_keyed_lock
from lightrag.constants import GRAPH_FIELD_SEP
from lightrag.utils import apply_source_ids_limit, compute_mdhash_id


def modal_chunk_id(content, doc_id):
    # A chunk belongs to one document in LightRAG. Identical multimodal content
    # in separate documents must survive deletion of either document.
    return compute_mdhash_id(
        f"{doc_id}\0{content}" if doc_id else content, prefix="chunk-"
    )


async def append_doc_index(storage, doc_id, field, additions, workspace):
    async with get_storage_keyed_lock(
        [doc_id], namespace=f"{workspace}:modal-doc-index"
    ):
        previous = await storage.get_by_id(doc_id) or {}
        values = previous.get(field, []) + additions
        if field == "relation_pairs":
            merged = [
                list(pair) for pair in dict.fromkeys(tuple(pair) for pair in values)
            ]
        else:
            merged = list(dict.fromkeys(values))
        await storage.upsert(
            {doc_id: {**previous, field: merged, "count": len(merged)}}
        )


class _IndexDelta:
    """Capture the document index produced by one LightRAG extraction pass."""

    def __init__(self):
        self.records = {}

    async def upsert(self, records):
        self.records.update(records)


async def merge_modal_graph(merge, lightrag, **kwargs):
    # LightRAG replaces the document index on each merge and swallows index
    # write errors. Append its deltas after the merge, before reporting success.
    entities, relations = _IndexDelta(), _IndexDelta()
    await merge(
        **kwargs,
        full_entities_storage=entities if lightrag.full_entities else None,
        full_relations_storage=relations if lightrag.full_relations else None,
    )
    for delta, storage, field in (
        (entities, lightrag.full_entities, "entity_names"),
        (relations, lightrag.full_relations, "relation_pairs"),
    ):
        for doc_id, record in delta.records.items():
            await append_doc_index(
                storage, doc_id, field, record[field], lightrag.workspace
            )


def caption_node(chunk_id, chunk):
    return {
        "entity_name": chunk["modal_entity_name"],
        "entity_type": chunk["modal_entity_type"],
        "description": chunk["modal_entity_summary"],
        "source_id": chunk_id,
        "file_path": chunk["file_path"],
    }


async def document_caption_entities(lightrag, doc_id, status):
    """Recover legacy caption membership before LightRAG reads the document index."""
    chunk_ids = (status or {}).get("chunks_list", [])
    if not chunk_ids:
        return []
    chunks = await lightrag.text_chunks.get_by_ids(chunk_ids)
    owners = {
        chunk["modal_entity_name"]
        for chunk in chunks
        if chunk and chunk.get("modal_entity_name")
    }
    legacy = {
        chunk["modal_entity_name"]
        for chunk in chunks
        if chunk
        and chunk.get("modal_entity_name")
        and "modal_entity_summary" not in chunk
    }
    if legacy:
        # Older writers overwrote both the document index and shared node sources.
        # Only registered chunk IDs identify owners reliably in that format.
        sources = {name: set() for name in legacy}
        legacy_ids = {
            key
            for key, chunk in zip(chunk_ids, chunks)
            if chunk and chunk.get("modal_entity_name") in legacy
        }
        page = 1
        while True:
            records, total = await lightrag.doc_status.get_docs_paginated(
                page=page, page_size=200, sort_field="id", sort_direction="asc"
            )
            for other_doc, record in records:
                ids = record.chunks_list or []
                if other_doc != doc_id and legacy_ids.intersection(ids):
                    raise ValueError(
                        "Legacy documents share chunk IDs. Rebuild these documents from source in a fresh workspace before deletion."
                    )
                if ids:
                    for key, chunk in zip(
                        ids, await lightrag.text_chunks.get_by_ids(ids)
                    ):
                        if chunk and chunk.get("modal_entity_name") in sources:
                            sources[chunk["modal_entity_name"]].add(key)
            if page * 200 >= total:
                break
            page += 1
        for name, ids in sources.items():
            async with graph_lock(lightrag, name):
                previous = await lightrag.entity_chunks.get_by_id(name) or {}
                node = await lightrag.chunk_entity_relation_graph.get_node(name)
                if node:
                    ids.update((node.get("source_id") or "").split(GRAPH_FIELD_SEP))
                ids.update(previous.get("chunk_ids", []))
                ids.discard("")
                await lightrag.entity_chunks.upsert(
                    {name: {"chunk_ids": sorted(ids), "count": len(ids)}}
                )
        await append_doc_index(
            lightrag.full_entities,
            doc_id,
            "entity_names",
            sorted(legacy),
            lightrag.workspace,
        )
    return sorted(owners)


def graph_lock(lightrag, name):
    workspace = lightrag.workspace
    return get_storage_keyed_lock(
        [name], namespace=f"{workspace}:GraphDB" if workspace else "GraphDB"
    )


async def refresh_surviving_captions(lightrag, names):
    """LightRAG can't replay a caption from its text-extraction response cache."""

    for name in names:
        async with graph_lock(lightrag, name):
            ownership = await lightrag.entity_chunks.get_by_id(name)
            if not ownership or not ownership.get("chunk_ids"):
                continue
            ids = apply_source_ids_limit(
                ownership["chunk_ids"],
                lightrag.max_source_ids_per_entity,
                lightrag.source_ids_limit_method,
            )
            if not ids:
                continue
            chunks = await lightrag.text_chunks.get_by_ids(ids)
            node = await lightrag.chunk_entity_relation_graph.get_node(name)
            if not node or not all(chunks):
                raise ValueError(
                    f"Missing indexed source data for surviving entity {name!r}"
                )
            node = dict(node)
            node["source_id"] = GRAPH_FIELD_SEP.join(ids)
            paths = list(dict.fromkeys(c["file_path"] for c in chunks))
            if len(paths) > lightrag.max_file_paths:
                retained = apply_source_ids_limit(
                    paths, lightrag.max_file_paths, lightrag.source_ids_limit_method
                )
                retained.append(
                    f"...{lightrag.file_path_more_placeholder}...({lightrag.source_ids_limit_method} {len(retained)}/{len(paths)})"
                )
                paths = retained
            node["file_path"] = GRAPH_FIELD_SEP.join(paths)
            if all(c.get("modal_entity_name") == name for c in chunks):
                node["description"] = GRAPH_FIELD_SEP.join(
                    dict.fromkeys(
                        c.get("modal_entity_summary") or c["content"] for c in chunks
                    )
                )
            await lightrag.chunk_entity_relation_graph.upsert_node(name, node)
            await lightrag.entities_vdb.upsert(
                {
                    compute_mdhash_id(name, prefix="ent-"): {
                        "entity_name": name,
                        "entity_type": node["entity_type"],
                        "source_id": node["source_id"],
                        "file_path": node["file_path"],
                        "content": f"{name}\n{node['description']}",
                    }
                }
            )
    if names:
        await lightrag._insert_done()

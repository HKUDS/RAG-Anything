# Chunk-Level Document Updates

When a small part of a large processed document changes, re-processing the
whole document re-extracts every chunk. RAGAnything can instead add, delete or
replace individual chunks of a document that is already in the knowledge
graph. Only the changed chunks are extracted, and the graph follows: an entity
or relation fed only by removed chunks is deleted, and one that other chunks
also feed is rebuilt from them.

The work is done by LightRAG. These methods forward to
`LightRAG.aadd_chunks_to_doc`, `adelete_chunks_from_doc` and
`amodify_chunk_in_doc`, so they need a `lightrag-hku` release that provides
them. With an older release they raise `NotImplementedError` naming the missing
method.

## Usage

```python
from raganything import RAGAnything

rag = RAGAnything(lightrag=lightrag_instance)  # or any configured instance

# Add: returns one generated chunk id per text, in order
ids = await rag.aadd_chunks_to_doc("doc-123", ["Rent is $2,000 per month."])

# Replace one chunk's text: returns the id of the chunk now holding it
new_id = await rag.amodify_chunk_in_doc(
    "doc-123", ids[0], "Rent is $2,150 per month."
)

# Delete: returns LightRAG's DeletionResult (check .status and .message)
result = await rag.adelete_chunks_from_doc("doc-123", [new_id])
```

Each method has a synchronous form: `add_chunks_to_doc`,
`modify_chunk_in_doc` and `delete_chunks_from_doc`.

## Behavior

- **The document must already be processed.** Adding never creates a
  document. Use `process_document_complete` or `insert_content_list` for new
  documents.
- **Chunk ids are generated from the document id and the text.** Store the ids
  `aadd_chunks_to_doc` returns, or recompute them with
  `lightrag.utils_pipeline.make_custom_chunk_id(doc_id, text)`. Text the
  document already holds is not added again, and its existing id is returned.
- **Deleting only touches chunks the document owns.** Other ids are skipped,
  and repeating a finished delete is a no-op.
  `delete_llm_cache=True` also removes the deleted chunks' extraction cache.
- **Modify adds before it deletes.** A failure leaves both versions rather than
  neither, and repeating the call finishes the job.
- **No parser is needed.** Like querying, these calls work on the LightRAG
  instance directly and do not require MinerU or another parser to be
  installed.
- **Re-processing the whole document undoes chunk-level edits.** It starts
  again from the originally stored text.

See LightRAG's
[Update Chunks in a Document](https://github.com/HKUDS/LightRAG/blob/main/docs/ProgramingWithCore.md)
for the full rules, including the result codes, locking and recovery.

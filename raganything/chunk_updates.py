"""
Chunk-level document updates for RAGAnything

Add, delete or replace some chunks of an already processed document without
re-processing all of it. The work is done by the LightRAG instance: these
methods forward to LightRAG's ``aadd_chunks_to_doc``,
``adelete_chunks_from_doc`` and ``amodify_chunk_in_doc``, which re-extract
only the changed chunks and keep the knowledge graph consistent.

They need a lightrag-hku release that provides those methods. With an older
one they raise ``NotImplementedError`` naming the missing method, instead of
failing with an ``AttributeError`` deep inside a call.
"""

from typing import Any, List

from lightrag.utils import always_get_an_event_loop


class ChunkUpdateMixin:
    """Chunk-level update methods, mixed into :class:`RAGAnything`."""

    def _lightrag_chunk_method(self, name: str):
        """Return LightRAG's chunk-level method ``name``, or explain why not.

        Unlike processing, these calls parse nothing, so they do not go through
        ``_ensure_lightrag_initialized`` and its parser check: like querying,
        they only need a LightRAG instance that already holds the document.
        """
        if self.lightrag is None:
            raise ValueError(
                "No LightRAG instance available. Please process documents first "
                "or provide a pre-initialized LightRAG instance."
            )
        method = getattr(self.lightrag, name, None)
        if method is None:
            raise NotImplementedError(
                f"The installed lightrag-hku does not provide LightRAG.{name}; "
                "chunk-level document updates need a release that does."
            )
        return method

    async def aadd_chunks_to_doc(self, doc_id: str, contents: List[str]) -> List[str]:
        """Add chunks to an existing processed document.

        Args:
            doc_id: The document to extend. It must already exist and be
                processed; this never creates one.
            contents: The text of each new chunk.

        Returns:
            One chunk id per distinct non-empty text, in input order. Ids are
            generated from the document id and the text. Text the document
            already holds is not added again, and its existing id is returned.
        """
        method = self._lightrag_chunk_method("aadd_chunks_to_doc")
        return await method(doc_id, contents)

    def add_chunks_to_doc(self, doc_id: str, contents: List[str]) -> List[str]:
        """Synchronous version of :meth:`aadd_chunks_to_doc`."""
        loop = always_get_an_event_loop()
        return loop.run_until_complete(self.aadd_chunks_to_doc(doc_id, contents))

    async def adelete_chunks_from_doc(
        self, doc_id: str, chunk_ids: List[str], delete_llm_cache: bool = False
    ) -> Any:
        """Delete some chunks of a processed document and keep the rest.

        Knowledge-graph entities and relations fed only by the removed chunks
        are deleted; shared ones are rebuilt from the chunks that remain.

        Args:
            doc_id: The document whose chunks are removed.
            chunk_ids: Chunk ids to remove. Ids the document does not own are
                skipped.
            delete_llm_cache: Also delete the removed chunks' extraction cache.

        Returns:
            LightRAG's ``DeletionResult``: check ``status`` (``success``,
            ``not_found``, ``not_allowed`` or ``fail``) and ``message``.
        """
        method = self._lightrag_chunk_method("adelete_chunks_from_doc")
        return await method(doc_id, chunk_ids, delete_llm_cache=delete_llm_cache)

    def delete_chunks_from_doc(
        self, doc_id: str, chunk_ids: List[str], delete_llm_cache: bool = False
    ) -> Any:
        """Synchronous version of :meth:`adelete_chunks_from_doc`."""
        loop = always_get_an_event_loop()
        return loop.run_until_complete(
            self.adelete_chunks_from_doc(
                doc_id, chunk_ids, delete_llm_cache=delete_llm_cache
            )
        )

    async def amodify_chunk_in_doc(
        self,
        doc_id: str,
        old_chunk_id: str,
        new_content: str,
        delete_llm_cache: bool = False,
    ) -> str:
        """Replace one chunk's text and keep the rest of the document.

        The new text is added before the old chunk is removed, so a failure
        leaves both versions rather than neither, and repeating the call
        finishes the job.

        Returns:
            The id of the chunk now holding ``new_content``.
        """
        method = self._lightrag_chunk_method("amodify_chunk_in_doc")
        return await method(
            doc_id, old_chunk_id, new_content, delete_llm_cache=delete_llm_cache
        )

    def modify_chunk_in_doc(
        self,
        doc_id: str,
        old_chunk_id: str,
        new_content: str,
        delete_llm_cache: bool = False,
    ) -> str:
        """Synchronous version of :meth:`amodify_chunk_in_doc`."""
        loop = always_get_an_event_loop()
        return loop.run_until_complete(
            self.amodify_chunk_in_doc(
                doc_id, old_chunk_id, new_content, delete_llm_cache=delete_llm_cache
            )
        )

"""Validate RetrieveTool with a fake RAGAnything-like object.

Usage:
    python -m rag_agent.agent.tools.validate_retrieve_tool
"""

from __future__ import annotations

import asyncio
import json

from rag_agent.agent.tools.retrieve import RetrieveTool


class _FakeLightRAG:
    async def aquery_data(self, query: str, param) -> dict:
        _ = param  # only to mirror signature
        return {
            "status": "success",
            "message": "Query executed successfully",
            "data": {
                "entities": [
                    {
                        "entity_name": "RAG",
                        "entity_type": "concept",
                        "description": "Retrieval-Augmented Generation",
                        "source_id": "chunk-1",
                        "file_path": "demo.pdf",
                        "reference_id": "[1]",
                    }
                ],
                "relationships": [],
                "chunks": [
                    {
                        "content": "RAG combines retrieval with generation.",
                        "file_path": "demo.pdf",
                        "chunk_id": "chunk-1",
                        "reference_id": "[1]",
                    }
                ],
                "references": [{"reference_id": "[1]", "file_path": "demo.pdf"}],
            },
            "metadata": {"query_mode": "hybrid"},
        }


class _FakeRAG:
    def __init__(self) -> None:
        self.lightrag = _FakeLightRAG()


async def main() -> None:
    tool = RetrieveTool(rag=_FakeRAG(), mode="hybrid", top_k=3, chunk_top_k=3)
    result = await tool.execute(query="what is rag")
    parsed = json.loads(result)

    assert parsed["status"] == "success"
    assert parsed["counts"]["chunks"] == 1
    assert parsed["evidence"]["entities"][0]["entity_name"] == "RAG"

    print("RETRIEVE_TOOL_TEST: PASS")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

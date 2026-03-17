"""Placeholder generate tool for RAG agent."""

from __future__ import annotations

from typing import Any

from .base import Tool


class GenerateTool(Tool):
    """Generate final answer from user question and retrieved context."""

    @property
    def name(self) -> str:
        return "generate"

    @property
    def description(self) -> str:
        return "Generate a grounded final answer using provided context chunks."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Original user question."},
                "context": {
                    "type": "string",
                    "description": "Retrieved context serialized as text.",
                },
            },
            "required": ["question", "context"],
        }

    async def execute(self, **kwargs: Any) -> str:
        # Placeholder implementation; replace with real generation in next step.
        question = kwargs.get("question", "")
        return f"[TODO] generate tool is not implemented yet. question={question}"

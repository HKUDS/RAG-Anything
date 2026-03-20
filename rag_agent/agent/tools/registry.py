"""Tool registry for the minimal RAG agent."""

from __future__ import annotations

from typing import Any

from .base import Tool


class ToolRegistry:
    """Manage tool registration, schema export, and execution dispatch."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register one tool instance."""
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_definitions(self) -> list[dict[str, Any]]:
        """Return all tool schemas in OpenAI function format."""
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute tool with safe cast + validation."""
        tool = self.get(name)
        if tool is None:
            return f"Tool not found: {name}"

        casted = tool.cast_params(arguments or {})
        errors = tool.validate_params(casted)
        if errors:
            return "Invalid tool arguments: " + "; ".join(errors)

        try:
            return await tool.execute(**casted)
        except Exception as exc:
            return f"Tool execution failed: {name}: {exc}"

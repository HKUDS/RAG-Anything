# -*- coding: utf-8 -*-
"""
Agentic RAG Base Types — Data Models + Tool ABC.

Layer: Core
Primary Responsibility: Foundational types shared by engine.py and tools.py —
    ReasoningStep, AgentResult, StreamEvent dataclasses, and Tool abstract base.
Key Dependencies: stdlib (dataclasses, abc, typing)

Extracted from engine.py to break circular import between engine ↔ tools.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ReasoningStep:
    """Single-step reasoning record."""
    step_number: int
    thought: str
    action: Optional[str] = None
    action_input: Optional[dict] = None
    observation: Optional[str] = None
    elapsed_ms: float = 0.0


@dataclass
class AgentResult:
    """Agentic RAG query result."""
    answer: str
    trace: list[ReasoningStep] = field(default_factory=list)
    total_steps: int = 0
    total_elapsed_ms: float = 0.0


@dataclass
class StreamEvent:
    """Streaming event yielded by run_stream()."""
    type: str  # "thinking" | "token" | "done"
    step: int | None = None
    thought: str | None = None
    action: str | None = None
    observation: str | None = None
    content: str | None = None
    elapsed_ms: float = 0.0
    # done event additional fields
    total_steps: int = 0
    answer: str = ""


class Tool(ABC):
    """Abstract tool base class.

    Subclasses must define:
        name: str           — tool name (used for ReAct Action matching)
        description: str    — tool description (injected into LLM prompt)
        parameters: dict    — JSON Schema parameter definition

    Subclasses must implement:
        async execute(input: dict) -> str
    """
    name: str = ""
    description: str = ""
    parameters: dict = {}

    @abstractmethod
    async def execute(self, input: dict) -> str:
        ...

    def to_schema(self) -> dict:
        """Return OpenAI function-calling format tool schema."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


__all__ = ["ReasoningStep", "AgentResult", "StreamEvent", "Tool"]

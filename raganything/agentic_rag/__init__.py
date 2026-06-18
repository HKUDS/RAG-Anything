# -*- coding: utf-8 -*-
"""
RAG-Anything Agentic RAG Sub-Package.

Layer: Core
Primary Responsibility: Agentic RAG reasoning engine — ReAct loop, CoT loop,
    tool framework, streaming agent responses.
Key Dependencies: lightrag (LightRAG), raganything (RAGAnything)

Call chain:
    AgenticRAG.run() / run_stream() / run_with_context()
      ├── _react_loop()          — ReAct (Reasoning+Acting) iterative loop
      │     ├── _call_llm_with_retry()  — LLM call with retry
      │     ├── _parse_action()          — Parse Thought/Action from LLM output
      │     ├── _execute_tool_with_timeout() — Tool execution with 30s timeout
      │     └── _force_final_answer()  — Fallback when max_steps exceeded
      └── _cot_loop()            — Chain-of-Thought single-pass reasoning

Built-in tools:
    SearchTool, CalculatorTool, DatabaseQueryTool, WebSearchTool

Sub-modules:
    tool_base.py — ReasoningStep, AgentResult, StreamEvent, Tool(ABC)
    engine.py    — AgenticRAG class (ReAct/COT engine, ~700 lines)
    tools.py     — SearchTool, CalculatorTool, DatabaseQueryTool, WebSearchTool
"""

from raganything.agentic_rag.tool_base import (
    ReasoningStep,
    AgentResult,
    StreamEvent,
    Tool,
)
from raganything.agentic_rag.engine import AgenticRAG
from raganything.agentic_rag.tools import (
    SearchTool,
    CalculatorTool,
    DatabaseQueryTool,
    WebSearchTool,
)

__all__ = [
    "ReasoningStep",
    "AgentResult",
    "StreamEvent",
    "Tool",
    "AgenticRAG",
    "SearchTool",
    "CalculatorTool",
    "DatabaseQueryTool",
    "WebSearchTool",
]

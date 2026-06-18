# -*- coding: utf-8 -*-
"""
Prompt Templates for Multimodal Content Processing.

Layer: Core
Primary Responsibility: All LLM/VLM prompt templates for modal processors —
    image analysis, table analysis, equation analysis, generic content,
    query formatting, citation instructions.
Key Dependencies: none (pure string templates)

Contains: PROMPTS dict with 30+ templates including:
    vision_prompt, table_prompt, equation_prompt, generic_prompt,
    image_chunk, table_chunk, equation_chunk, generic_chunk,
    IMAGE_ANALYSIS_SYSTEM, TABLE_ANALYSIS_SYSTEM, EQUATION_ANALYSIS_SYSTEM,
    query templates, citation format instructions
"""

from __future__ import annotations
from collections.abc import ItemsView, Iterator, KeysView, ValuesView
from typing import Any


class PromptRegistry:
    """Stable prompt container with atomic snapshot swapping.

    Readers keep a reference to this object, while language switches replace the
    underlying prompt dictionary in one step via :meth:`swap`.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def swap(self, prompts: dict[str, Any]) -> None:
        """Atomically replace the active prompt snapshot."""
        self._data = dict(prompts)

    def snapshot(self) -> dict[str, Any]:
        """Return a copy of the active prompt set."""
        return dict(self._data)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def keys(self) -> KeysView[str]:
        return self._data.keys()

    def items(self) -> ItemsView[str, Any]:
        return self._data.items()

    def values(self) -> ValuesView[Any]:
        return self._data.values()

    def __repr__(self) -> str:
        return f"PromptRegistry({self._data!r})"


PROMPTS = PromptRegistry()

# System prompts for different analysis types
PROMPTS["IMAGE_ANALYSIS_SYSTEM"] = (
    "You are an expert image analyst. Provide detailed, accurate descriptions."
)
PROMPTS["IMAGE_ANALYSIS_FALLBACK_SYSTEM"] = (
    "You are an expert image analyst. Provide detailed analysis based on available information."
)
PROMPTS["TABLE_ANALYSIS_SYSTEM"] = (
    "You are an expert data analyst. Provide detailed table analysis with specific insights."
)
PROMPTS["EQUATION_ANALYSIS_SYSTEM"] = (
    "You are an expert mathematician. Provide detailed mathematical analysis."
)
PROMPTS["GENERIC_ANALYSIS_SYSTEM"] = (
    "You are an expert content analyst specializing in {content_type} content."
)
PROMPTS["VIDEO_ANALYSIS_SYSTEM"] = (
    "You are an expert video analyst. Provide comprehensive analysis synthesizing visual frames, "
    "audio transcripts, temporal structure, and video metadata. Focus on key events, topics, "
    "speakers, visual changes, and the overall narrative arc of the video content."
)

# Image analysis prompt template
PROMPTS[
    "vision_prompt"
] = """Please analyze this image in detail and provide a JSON response with the following structure:

{{
    "detailed_description": "A comprehensive and detailed visual description of the image following these guidelines:
    - Describe the overall composition and layout
    - Identify all objects, people, text, and visual elements
    - Explain relationships between elements
    - Note colors, lighting, and visual style
    - Describe any actions or activities shown
    - Include technical details if relevant (charts, diagrams, etc.)
    - Always use specific names instead of pronouns",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "image",
        "summary": "concise summary of the image content and its significance (max 100 words)"
    }}
}}

Additional context:
- Section Path: {section_path}
- Image Path: {image_path}
- Captions: {captions}
- Footnotes: {footnotes}

Focus on providing accurate, detailed visual analysis that would be useful for knowledge retrieval.
Use a semantic entity_name; do not return file names or figure numbers such as figure_30_1 unless they are the actual title."""

# Image analysis prompt with context support
PROMPTS[
    "vision_prompt_with_context"
] = """Please analyze this image in detail, considering the surrounding context. Provide a JSON response with the following structure:

{{
    "detailed_description": "A comprehensive and detailed visual description of the image following these guidelines:
    - Describe the overall composition and layout
    - Identify all objects, people, text, and visual elements
    - Explain relationships between elements and how they relate to the surrounding context
    - Note colors, lighting, and visual style
    - Describe any actions or activities shown
    - Include technical details if relevant (charts, diagrams, etc.)
    - Reference connections to the surrounding content when relevant
    - Always use specific names instead of pronouns",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "image",
        "summary": "concise summary of the image content, its significance, and relationship to surrounding content (max 100 words)"
    }}
}}

Context from surrounding content:
{context}

Document structure:
- Section Path: {section_path}

Image details:
- Image Path: {image_path}
- Captions: {captions}
- Footnotes: {footnotes}

Focus on providing accurate, detailed visual analysis that incorporates the context and would be useful for knowledge retrieval.
Use a semantic entity_name; do not return file names or figure numbers such as figure_30_1 unless they are the actual title."""

# Image analysis prompt with text fallback
PROMPTS["text_prompt"] = """Based on the following image information, provide analysis:

Image Path: {image_path}
Captions: {captions}
Footnotes: {footnotes}

{vision_prompt}"""

# Table analysis prompt template
PROMPTS[
    "table_prompt"
] = """Analyze this table and return JSON:

{{
    "detailed_description": "Analyze table structure, column meanings, key data, trends, and relationships. Use specific names and values.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "table",
        "summary": "table purpose and key findings (max 100 words)"
    }}
}}

Table: {table_caption}
Body: {table_body}
Footnotes: {table_footnote}"""

# Table analysis prompt with context support
PROMPTS[
    "table_prompt_with_context"
] = """Analyze this table considering surrounding context, return JSON:

{{
    "detailed_description": "Analyze table structure, column meanings, key data, trends, and relationship to surrounding context. Use specific names and values.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "table",
        "summary": "table purpose, key findings, and context relationship (max 100 words)"
    }}
}}

Surrounding context:
{context}

Table: {table_caption}
Body: {table_body}
Footnotes: {table_footnote}"""

# Equation analysis prompt template
PROMPTS[
    "equation_prompt"
] = """Please analyze this mathematical equation and provide a JSON response with the following structure:

{{
    "detailed_description": "A comprehensive analysis of the equation including:
    - Mathematical meaning and interpretation
    - Variables and their definitions
    - Mathematical operations and functions used
    - Application domain and context
    - Physical or theoretical significance
    - Relationship to other mathematical concepts
    - Practical applications or use cases
    Always use specific mathematical terminology.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "equation",
        "summary": "concise summary of the equation's purpose and significance (max 100 words)"
    }}
}}

Equation Information:
Equation: {equation_text}
Format: {equation_format}

Focus on providing mathematical insights and explaining the equation's significance."""

# Equation analysis prompt with context support
PROMPTS[
    "equation_prompt_with_context"
] = """Please analyze this mathematical equation considering the surrounding context, and provide a JSON response with the following structure:

{{
    "detailed_description": "A comprehensive analysis of the equation including:
    - Mathematical meaning and interpretation
    - Variables and their definitions in the context of surrounding content
    - Mathematical operations and functions used
    - Application domain and context based on surrounding material
    - Physical or theoretical significance
    - Relationship to other mathematical concepts mentioned in the context
    - Practical applications or use cases
    - How the equation relates to the broader discussion or framework
    Always use specific mathematical terminology.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "equation",
        "summary": "concise summary of the equation's purpose, significance, and role in the surrounding context (max 100 words)"
    }}
}}

Context from surrounding content:
{context}

Equation Information:
Equation: {equation_text}
Format: {equation_format}

Focus on providing mathematical insights and explaining the equation's significance within the broader context."""

# Generic content analysis prompt template
PROMPTS[
    "generic_prompt"
] = """Analyze this {content_type} content and return JSON:

{{
    "detailed_description": "Analyze structure, key info, relationships, context, and knowledge-retrieval-relevant details. Use {content_type}-appropriate terminology.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "{content_type}",
        "summary": "concise summary (max 100 words)"
    }}
}}

Content: {content}"""

# Generic content analysis prompt with context support
PROMPTS[
    "generic_prompt_with_context"
] = """Analyze this {content_type} content considering surrounding context, return JSON:

{{
    "detailed_description": "Analyze structure, key info, relationships, and connection to surrounding context. Use {content_type}-appropriate terminology.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "{content_type}",
        "summary": "concise summary including context relationship (max 100 words)"
    }}
}}

Surrounding context:
{context}

Content: {content}"""

# Video analysis prompt template
PROMPTS[
    "video_prompt"
] = """Please analyze this video content comprehensively, synthesizing visual frames, audio transcript, and temporal structure. Provide a JSON response with the following structure:

{{
    "detailed_description": "A comprehensive analysis of the video including:
    - Overall topic and purpose of the video
    - Key events and their temporal sequence
    - Visual content: main scenes, people, objects, text, diagrams shown
    - Audio content: main topics discussed, key statements, speaker tone
    - How visual and audio elements complement each other
    - Important transitions or turning points
    - Summary of the complete narrative or information presented
    Always use specific names, timestamps, and concrete details.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "video",
        "summary": "concise summary of the video's overall content and significance (max 100 words)"
    }}
}}

Video details:
- Video Path: {video_path}
- Duration: {duration}s
- Frames Extracted: {frame_count}

Frame Descriptions:
{frame_descriptions}

Audio Transcript:
{transcript}

Context from surrounding document:
{context}

Synthesize all available information (frames, transcript, metadata) into a unified analysis."""

# Video analysis prompt with context support
PROMPTS[
    "video_prompt_with_context"
] = """Please analyze this video content considering both its internal content and the surrounding document context. Provide a JSON response with the following structure:

{{
    "detailed_description": "A comprehensive analysis of the video including:
    - Overall topic and purpose of the video
    - Key events and their temporal sequence
    - Visual content: main scenes, people, objects, text, diagrams shown
    - Audio content: main topics discussed, key statements, speaker tone
    - How visual and audio elements complement each other
    - Important transitions or turning points
    - How the video relates to the surrounding document context
    - Summary of the complete narrative or information presented
    Always use specific names, timestamps, and concrete details.",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "video",
        "summary": "concise summary of the video's content, significance, and role in the broader document (max 100 words)"
    }}
}}

Context from surrounding document:
{context}

Video details:
- Video Path: {video_path}
- Duration: {duration}s
- Frames Extracted: {frame_count}

Frame Descriptions:
{frame_descriptions}

Audio Transcript:
{transcript}

Synthesize all available information (frames, transcript, metadata, context) into a unified analysis."""

# Modal chunk templates
PROMPTS["image_chunk"] = """
Image Content Analysis:
- Section Path: {section_path}
- Neighbor Text: {neighbor_text}
Image Path: {image_path}
Captions: {captions}
Footnotes: {footnotes}

Visual Analysis: {enhanced_caption}"""

PROMPTS["table_chunk"] = """Table Analysis:
Caption: {table_caption}
Footnotes: {table_footnote}

Analysis: {enhanced_caption}

Raw Structure (simplified): {table_body}"""

PROMPTS["equation_chunk"] = """Mathematical Equation Analysis:
Equation: {equation_text}
Format: {equation_format}

Mathematical Analysis: {enhanced_caption}"""

PROMPTS["generic_chunk"] = """{content_type} Content Analysis:
Content: {content}

Analysis: {enhanced_caption}"""

PROMPTS["video_chunk"] = """Video Content Analysis:
- Video Path: {video_path}
- Duration: {duration}s
- Estimated Frames: {frame_count}

Transcript Preview: {transcript_summary}

Comprehensive Video Analysis: {enhanced_caption}"""

# Query-related prompts
PROMPTS["QUERY_IMAGE_DESCRIPTION"] = (
    "Please briefly describe the main content, key elements, and important information in this image."
)

PROMPTS["QUERY_IMAGE_ANALYST_SYSTEM"] = (
    "You are a professional image analyst who can accurately describe image content."
)

PROMPTS[
    "QUERY_TABLE_ANALYSIS"
] = """Please analyze the main content, structure, and key information of the following table data:

Table data:
{table_data}

Table caption: {table_caption}

Please briefly summarize the main content, data characteristics, and important findings of the table."""

PROMPTS["QUERY_TABLE_ANALYST_SYSTEM"] = (
    "You are a professional data analyst who can accurately analyze table data."
)

PROMPTS[
    "QUERY_EQUATION_ANALYSIS"
] = """Please explain the meaning and purpose of the following mathematical formula:

LaTeX formula: {latex}
Formula caption: {equation_caption}

Please briefly explain the mathematical meaning, application scenarios, and importance of this formula."""

PROMPTS["QUERY_EQUATION_ANALYST_SYSTEM"] = (
    "You are a mathematics expert who can clearly explain mathematical formulas."
)

PROMPTS[
    "QUERY_GENERIC_ANALYSIS"
] = """Please analyze the following {content_type} type content and extract its main information and key features:

Content: {content_str}

Please briefly summarize the main characteristics and important information of this content."""

PROMPTS["QUERY_GENERIC_ANALYST_SYSTEM"] = (
    "You are a professional content analyst who can accurately analyze {content_type} type content."
)

PROMPTS["QUERY_ENHANCEMENT_SUFFIX"] = (
    "\n\nPlease provide a comprehensive answer based on the user query and the provided multimodal content information."
)

# Conversation context template (for multi-turn dialogue memory)
PROMPTS["CONVERSATION_CONTEXT_TEMPLATE"] = (
    "## Conversation History\n"
    "{history}\n\n"
    "## Retrieved Documents\n"
    "{documents}\n\n"
    "## Current Question\n"
    "{query}"
)

# Inline source quoting instruction — injected into LLM prompts to require
# direct quoting of original retrieval content within the answer text.
#
# This asks the LLM to:
# 1. Embed original text excerpts inline when citing retrieval content
# 2. Use quotation marks to demarcate quoted text
# 3. Copy verbatim (at least 20 chars), no paraphrasing
INLINE_QUOTE_INSTRUCTION = (
    "## 回答要求\n"
    "1. 引用检索内容中的事实或数据时，必须用引号直接嵌入原文，"
    "格式：\"原文摘录...\"。\n"
    "2. 原文摘录必须逐字复制（至少20字），不可概括或改写。\n"
    "3. 检索内容中的每条信息都以 `[来源 文档名]` 标注。"
    "引用时在句末标注 `[来源 文档名]`。如果没有文档名，只引原文即可，**不要**自己编造来源名称。\n"
    "4. 每个要点只引用 1-2 处关键原文，保持回答简洁流畅。\n"
    "5. 检索内容中无相关信息时说\"未找到\"，不要编造。\n"
    "6. 严禁在回答中使用以下系统内部术语：\"code\"、\"实体描述\"、\"entity_type\"、\"chunk_id\"、\"relationship\"。\n"
    "7. 禁止使用 [来源 N]（数字编号）格式，必须用 `[来源 文档名]`。"
)

# Mandatory citation and answer format instruction — replaces INLINE_QUOTE_INSTRUCTION
# for queries with enforce_citation enabled (default).
#
# Design principles:
# 1. Short (~250 chars) to minimize context-window cost
# 2. Natural language — avoid rigid three-section template for simple answers
# 3. Entity-relation citation only required when relation paths appear in context
ANSWER_FORMAT_INSTRUCTION = (
    "## 回答要求（必须遵守）\n\n"
    "### 引用格式\n"
    "1. 每条事实性陈述必须用文档名标注来源。检索上下文中每条信息都标记了来源。\n"
    "   格式：文章中说明系统包含六个模块[来源 毕业设计论文]。\n"
    "   即用 `[来源 文档名]` 紧跟在被引用的陈述之后。\n"
    "2. 引用原文时用引号括起并逐字复制（至少20字）：\n"
    '   "原文摘录内容..."[来源 毕业设计论文]。\n'
    "3. 每个要点最多引用 1-2 处原文。无相关信息时说\"未找到\"，绝不编造。\n"
    "\n"
    "### 参考文献块\n"
    "4. 回答末尾必须附加以下格式的参考文献块：\n"
    "```\n"
    "📚 参考来源\n"
    '[来源 毕业设计论文] — "原文摘录内容..."\n'
    '[来源 系统设计文档] — "原文摘录内容..."\n'
    "```\n"
    "5. 检索内容中如有实体关系信息，在正文中用自然语句说明，"
    "并在参考文献块后附加关联实体摘要，格式：\n"
    "   `- 实体A → 实体B（关系类型）`\n"
    "   无关联实体信息则省略此部分。\n"
    "\n"
    "### 严格禁止\n"
    "6. 以下技术元数据术语绝对禁止出现在最终回答中：\n"
    "   \"code\"、\"实体描述\"、\"entity_type\"、\"chunk_id\"、\n"
    "   \"source\"（指 chunk 编号）、\"entity_name\"、\"relation_pairs\"、\n"
    "   \"relationship\"、以及任何形如 [来源 N]（其中 N 是数字编号）。\n"
    "   引用来源必须用文档名，不得用数字编号。"
)

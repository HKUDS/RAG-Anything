"""
Chinese (中文) prompt templates for multimodal content processing.

Provides Chinese-language prompt templates as an alternative to the default
English templates.  Users can activate these at process level by calling
``set_prompt_language("zh")`` from :mod:`raganything.prompt_manager`.

Addresses GitHub issue #85 — prompt language support.
"""

from __future__ import annotations
from typing import Any

PROMPTS_ZH: dict[str, Any] = {}

# System prompts for different analysis types
PROMPTS_ZH["IMAGE_ANALYSIS_SYSTEM"] = (
    "你是一位专业的图像分析专家。请提供详细、准确的描述。"
    "所有自然语言输出，包括图片名称、详细描述和摘要，都必须使用简体中文；"
    "图片中的原文、公式、型号和无法翻译的专有名词可以按需保留。"
)
PROMPTS_ZH["IMAGE_ANALYSIS_FALLBACK_SYSTEM"] = (
    "你是一位专业的图像分析专家。请根据现有信息提供详细分析。"
    "所有自然语言输出必须使用简体中文；原文、公式、型号和专有名词可以按需保留。"
)
PROMPTS_ZH["TABLE_ANALYSIS_SYSTEM"] = (
    "你是一位专业的数据分析师。请提供包含具体洞察的详细表格分析。"
)
PROMPTS_ZH["EQUATION_ANALYSIS_SYSTEM"] = "你是一位数学专家。请提供详细的数学分析。"
PROMPTS_ZH["GENERIC_ANALYSIS_SYSTEM"] = "你是一位专注于{content_type}内容的专业分析师。"
PROMPTS_ZH["VIDEO_ANALYSIS_SYSTEM"] = (
    "你是一位专业的视频分析师。请提供综合分析，综合视觉帧、"
    "音频转录、时间结构和视频元数据。重点关注关键事件、主题、"
    "发言人、视觉变化以及视频内容的整体叙事线索。"
)

# Image analysis prompt template
PROMPTS_ZH["vision_prompt"] = """请详细分析这张图片，并以以下JSON结构提供回答：

{{
    "detailed_description": "对图片的全面详细描述，遵循以下指导：
    - 描述整体构图和布局
    - 识别所有对象、人物、文字和视觉元素
    - 解释元素之间的关系
    - 注意颜色、光照和视觉风格
    - 描述展示的任何动作或活动
    - 如涉及图表、图解等，包含技术细节
    - 始终使用具体名称而非代词",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "image",
        "summary": "图片内容及其重要性的简明摘要（不超过100字）"
    }}
}}

附加信息：
- 章节路径：{section_path}
- 图片路径：{image_path}
- 标注：{captions}
- 脚注：{footnotes}

请专注于提供准确、详细的视觉分析，以便于知识检索。
输出语言要求：detailed_description、entity_name 和 summary 必须使用简体中文；图片原文、公式、型号和专有名词可保留原样。
请生成语义化的 entity_name；不要返回文件名或图号（例如 figure_30_1），除非它们就是正式标题。"""

# Image analysis prompt with context support
PROMPTS_ZH[
    "vision_prompt_with_context"
] = """请结合上下文详细分析这张图片，并以以下JSON结构提供回答：

{{
    "detailed_description": "对图片的全面详细描述，遵循以下指导：
    - 描述整体构图和布局
    - 识别所有对象、人物、文字和视觉元素
    - 解释元素之间的关系及其与上下文的联系
    - 注意颜色、光照和视觉风格
    - 描述展示的任何动作或活动
    - 如涉及图表、图解等，包含技术细节
    - 在相关时引用与周围内容的联系
    - 始终使用具体名称而非代词",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "image",
        "summary": "图片内容、重要性及与周围内容关系的简明摘要（不超过100字）"
    }}
}}

周围内容上下文：
{context}

文档结构：
- 章节路径：{section_path}

图片详细信息：
- 图片路径：{image_path}
- 标注：{captions}
- 脚注：{footnotes}

请专注于提供融合上下文的准确、详细的视觉分析，以便于知识检索。
输出语言要求：detailed_description、entity_name 和 summary 必须使用简体中文；图片原文、公式、型号和专有名词可保留原样。
请生成语义化的 entity_name；不要返回文件名或图号（例如 figure_30_1），除非它们就是正式标题。"""

# Image analysis prompt with text fallback
PROMPTS_ZH["text_prompt"] = """根据以下图片信息提供分析：

图片路径：{image_path}
标注：{captions}
脚注：{footnotes}

{vision_prompt}"""

# Table analysis prompt template
PROMPTS_ZH["table_prompt"] = """分析此表格，返回JSON：

{{
    "detailed_description": "分析表格结构、列含义、关键数据、趋势及数据间关系。使用具体数值和名称。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "table",
        "summary": "表格目的和关键发现（≤100字）"
    }}
}}

表格：{table_caption}
内容：{table_body}
脚注：{table_footnote}"""

# Table analysis prompt with context support
PROMPTS_ZH[
    "table_prompt_with_context"
] = """结合上下文分析此表格，返回JSON：

{{
    "detailed_description": "分析表格结构、列含义、关键数据、趋势，及其与上下文的关系。使用具体数值和名称。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "table",
        "summary": "表格目的、关键发现及上下文关系（≤100字）"
    }}
}}

周围上下文：
{context}

表格：{table_caption}
内容：{table_body}
脚注：{table_footnote}"""

# Equation analysis prompt template
PROMPTS_ZH["equation_prompt"] = """请分析此数学公式，并以以下JSON结构提供回答：

{{
    "detailed_description": "对公式的全面分析，包括：
    - 数学含义和解释
    - 变量及其定义
    - 使用的数学运算和函数
    - 应用领域和背景
    - 物理或理论意义
    - 与其他数学概念的关系
    - 实际应用或用例
    始终使用准确的数学术语。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "equation",
        "summary": "公式目的和重要性的简明摘要（不超过100字）"
    }}
}}

公式信息：
公式：{equation_text}
格式：{equation_format}

请专注于提供数学洞察和解释公式的重要性。"""

# Equation analysis prompt with context support
PROMPTS_ZH[
    "equation_prompt_with_context"
] = """请结合上下文分析此数学公式，并以以下JSON结构提供回答：

{{
    "detailed_description": "对公式的全面分析，包括：
    - 数学含义和解释
    - 在上下文中变量的定义
    - 使用的数学运算和函数
    - 基于周围材料的应用领域和背景
    - 物理或理论意义
    - 与上下文中提到的其他数学概念的关系
    - 实际应用或用例
    - 公式如何与更广泛的讨论或框架相关联
    始终使用准确的数学术语。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "equation",
        "summary": "公式目的、重要性及在上下文中作用的简明摘要（不超过100字）"
    }}
}}

周围内容上下文：
{context}

公式信息：
公式：{equation_text}
格式：{equation_format}

请专注于在更广泛的上下文中提供数学洞察和解释公式的重要性。"""

# Generic content analysis prompt template
PROMPTS_ZH["generic_prompt"] = """分析此{content_type}内容，返回JSON：

{{
    "detailed_description": "分析内容结构、关键信息、元素关系、背景及知识检索相关细节。使用{content_type}领域专业术语。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "{content_type}",
        "summary": "内容要点摘要（≤100字）"
    }}
}}

内容：{content}"""

# Generic content analysis prompt with context support
PROMPTS_ZH[
    "generic_prompt_with_context"
] = """结合上下文分析此{content_type}内容，返回JSON：

{{
    "detailed_description": "分析内容结构、关键信息、元素关系，及其与周围上下文的关联。使用{content_type}领域专业术语。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "{content_type}",
        "summary": "内容要点及与上下文关系摘要（≤100字）"
    }}
}}

周围上下文：
{context}

内容：{content}"""

# Video analysis prompt template
PROMPTS_ZH[
    "video_prompt"
] = """请综合分析此视频内容，综合视觉帧、音频转录和时间结构。请以以下JSON格式提供回答：

{{
    "detailed_description": "视频的全面分析，包括：
    - 视频的整体主题和目的
    - 关键事件及其时间顺序
    - 视觉内容：主要场景、人物、物体、文本、图表
    - 音频内容：讨论的主要话题、关键陈述、发言人语气
    - 视觉和音频元素如何相互补充
    - 重要的转折点或过渡
    - 完整叙述或所呈现信息的总结
    始终使用具体的名称、时间戳和细节。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "video",
        "summary": "视频整体内容和重要性的简明摘要（不超过100字）"
    }}
}}

视频详情：
- 视频路径：{video_path}
- 时长：{duration}秒
- 提取帧数：{frame_count}

帧描述：
{frame_descriptions}

音频转录：
{transcript}

周围文档上下文：
{context}

请综合所有可用信息（帧、转录、元数据）形成统一分析。"""

# Video analysis prompt with context support
PROMPTS_ZH[
    "video_prompt_with_context"
] = """请结合其内部内容和周围文档上下文分析此视频。请以以下JSON格式提供回答：

{{
    "detailed_description": "视频的全面分析，包括：
    - 视频的整体主题和目的
    - 关键事件及其时间顺序
    - 视觉内容：主要场景、人物、物体、文本、图表
    - 音频内容：讨论的主要话题、关键陈述、发言人语气
    - 视觉和音频元素如何相互补充
    - 重要的转折点或过渡
    - 视频如何与周围文档上下文相关联
    - 完整叙述或所呈现信息的总结
    始终使用具体的名称、时间戳和细节。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "video",
        "summary": "视频内容、重要性及在更广泛文档中的作用的简明摘要（不超过100字）"
    }}
}}

周围文档上下文：
{context}

视频详情：
- 视频路径：{video_path}
- 时长：{duration}秒
- 提取帧数：{frame_count}

帧描述：
{frame_descriptions}

音频转录：
{transcript}

请综合所有可用信息（帧、转录、元数据、上下文）形成统一分析。"""

# Modal chunk templates
PROMPTS_ZH["image_chunk"] = """
图片内容分析：
- 章节路径：{section_path}
- 邻近文本：{neighbor_text}
图片路径：{image_path}
标注：{captions}
脚注：{footnotes}

视觉分析：{enhanced_caption}"""

PROMPTS_ZH["table_chunk"] = """表格分析：
标题：{table_caption}
脚注：{table_footnote}

分析：{enhanced_caption}

原始结构（简化）：{table_body}"""

PROMPTS_ZH["equation_chunk"] = """数学公式分析：
公式：{equation_text}
格式：{equation_format}

数学分析：{enhanced_caption}"""

PROMPTS_ZH["generic_chunk"] = """{content_type}内容分析：
内容：{content}

分析：{enhanced_caption}"""

# Query-related prompts
PROMPTS_ZH["QUERY_IMAGE_DESCRIPTION"] = (
    "请简要描述这张图片的主要内容、关键元素和重要信息。"
)

PROMPTS_ZH["QUERY_IMAGE_ANALYST_SYSTEM"] = (
    "你是一位能准确描述图片内容的专业图像分析师。"
)

PROMPTS_ZH["QUERY_TABLE_ANALYSIS"] = """请分析以下表格数据的主要内容、结构和关键信息：

表格数据：
{table_data}

表格标题：{table_caption}

请简要总结表格的主要内容、数据特征和重要发现。"""

PROMPTS_ZH["QUERY_TABLE_ANALYST_SYSTEM"] = (
    "你是一位能准确分析表格数据的专业数据分析师。"
)

PROMPTS_ZH["QUERY_EQUATION_ANALYSIS"] = """请解释以下数学公式的含义和用途：

LaTeX公式：{latex}
公式标题：{equation_caption}

请简要说明这个公式的数学意义、应用场景和重要性。"""

PROMPTS_ZH["QUERY_EQUATION_ANALYST_SYSTEM"] = "你是一位能清晰解释数学公式的数学专家。"

PROMPTS_ZH[
    "QUERY_GENERIC_ANALYSIS"
] = """请分析以下{content_type}类型内容并提取其主要信息和关键特征：

内容：{content_str}

请简要总结此内容的主要特征和重要信息。"""

PROMPTS_ZH["QUERY_GENERIC_ANALYST_SYSTEM"] = (
    "你是一位能准确分析{content_type}类型内容的专业内容分析师。"
)

PROMPTS_ZH["QUERY_ENHANCEMENT_SUFFIX"] = (
    "\n\n请基于用户查询和提供的多模态内容信息，提供全面的回答。"
)

# 对话上下文模板（多轮对话记忆）
PROMPTS_ZH["CONVERSATION_CONTEXT_TEMPLATE"] = (
    "## 对话历史\n"
    "{history}\n\n"
    "## 检索到的相关文档\n"
    "{documents}\n\n"
    "## 当前问题\n"
    "{query}"
)

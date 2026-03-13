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
)
PROMPTS_ZH["IMAGE_ANALYSIS_FALLBACK_SYSTEM"] = (
    "你是一位专业的图像分析专家。请根据现有信息提供详细分析。"
)
PROMPTS_ZH["TABLE_ANALYSIS_SYSTEM"] = (
    "你是一位专业的数据分析师。请提供包含具体洞察的详细表格分析。"
)
PROMPTS_ZH["EQUATION_ANALYSIS_SYSTEM"] = "你是一位数学专家。请提供详细的数学分析。"
PROMPTS_ZH["GENERIC_ANALYSIS_SYSTEM"] = "你是一位专注于{content_type}内容的专业分析师。"

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
- 图片路径：{image_path}
- 标注：{captions}
- 脚注：{footnotes}

请专注于提供准确、详细的视觉分析，以便于知识检索。"""

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

图片详细信息：
- 图片路径：{image_path}
- 标注：{captions}
- 脚注：{footnotes}

请专注于提供融合上下文的准确、详细的视觉分析，以便于知识检索。"""

# Image analysis prompt with text fallback
PROMPTS_ZH["text_prompt"] = """根据以下图片信息提供分析：

图片路径：{image_path}
标注：{captions}
脚注：{footnotes}

{vision_prompt}"""

# Table analysis prompt template
PROMPTS_ZH["table_prompt"] = """请分析此表格内容，并以以下JSON结构提供回答：

{{
    "detailed_description": "对表格的全面分析，包括：
    - 表格结构和组织方式
    - 列标题及其含义
    - 关键数据点和模式
    - 统计洞察和趋势
    - 数据元素之间的关系
    - 所呈现数据的重要性
    始终使用具体名称和数值而非笼统引用。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "table",
        "summary": "表格目的和关键发现的简明摘要（不超过100字）"
    }}
}}

表格信息：
图片路径：{table_img_path}
标题：{table_caption}
内容：{table_body}
脚注：{table_footnote}

请专注于从表格数据中提取有意义的洞察和关系。"""

# Table analysis prompt with context support
PROMPTS_ZH[
    "table_prompt_with_context"
] = """请结合上下文分析此表格内容，并以以下JSON结构提供回答：

{{
    "detailed_description": "对表格的全面分析，包括：
    - 表格结构和组织方式
    - 列标题及其含义
    - 关键数据点和模式
    - 统计洞察和趋势
    - 数据元素之间的关系
    - 所呈现数据与周围上下文的重要性
    - 表格如何支持或说明周围内容中的概念
    始终使用具体名称和数值而非笼统引用。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "table",
        "summary": "表格目的、关键发现及与周围内容关系的简明摘要（不超过100字）"
    }}
}}

周围内容上下文：
{context}

表格信息：
图片路径：{table_img_path}
标题：{table_caption}
内容：{table_body}
脚注：{table_footnote}

请专注于在上下文背景下从表格数据中提取有意义的洞察和关系。"""

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
PROMPTS_ZH["generic_prompt"] = """请分析此{content_type}内容，并以以下JSON结构提供回答：

{{
    "detailed_description": "对内容的全面分析，包括：
    - 内容结构和组织
    - 关键信息和元素
    - 组件之间的关系
    - 背景和重要性
    - 与知识检索相关的细节
    始终使用适合{content_type}内容的专业术语。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "{content_type}",
        "summary": "内容目的和要点的简明摘要（不超过100字）"
    }}
}}

内容：{content}

请专注于提取对知识检索有用的有意义信息。"""

# Generic content analysis prompt with context support
PROMPTS_ZH[
    "generic_prompt_with_context"
] = """请结合上下文分析此{content_type}内容，并以以下JSON结构提供回答：

{{
    "detailed_description": "对内容的全面分析，包括：
    - 内容结构和组织
    - 关键信息和元素
    - 组件之间的关系
    - 与周围内容相关的背景和重要性
    - 此内容如何与更广泛的讨论相联系或支持
    - 与知识检索相关的细节
    始终使用适合{content_type}内容的专业术语。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "{content_type}",
        "summary": "内容目的、要点及与周围上下文关系的简明摘要（不超过100字）"
    }}
}}

周围内容上下文：
{context}

内容：{content}

请专注于提取对知识检索有用的信息，并理解内容在更广泛上下文中的作用。"""

# Modal chunk templates
PROMPTS_ZH["image_chunk"] = """
图片内容分析：
图片路径：{image_path}
标注：{captions}
脚注：{footnotes}

视觉分析：{enhanced_caption}"""

PROMPTS_ZH["table_chunk"] = """表格分析：
图片路径：{table_img_path}
标题：{table_caption}
结构：{table_body}
脚注：{table_footnote}

分析：{enhanced_caption}"""

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

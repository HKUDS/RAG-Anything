"""
Traditional Chinese (繁體中文) prompt templates for multimodal content processing.

Provides Traditional Chinese (zh-tw / zh-hant) prompt templates as an alternative
to the default English and Simplified Chinese templates. Users can activate these
at process level by calling ``set_prompt_language("zh-tw")`` from :mod:`raganything.prompt_manager`.

Addresses GitHub issue #79 — Traditional Chinese prompt localization & page citation grounding.
"""

from __future__ import annotations
from typing import Any

PROMPTS_ZH_TW: dict[str, Any] = {}

# System prompts for different analysis types
PROMPTS_ZH_TW["IMAGE_ANALYSIS_SYSTEM"] = (
    "你是一位專業的圖像分析專家。請提供詳細、準確的描述。"
)
PROMPTS_ZH_TW["IMAGE_ANALYSIS_FALLBACK_SYSTEM"] = (
    "你是一位專業的圖像分析專家。請根據現有資訊提供詳細分析。"
)
PROMPTS_ZH_TW["TABLE_ANALYSIS_SYSTEM"] = (
    "你是一位專業的資料分析師。請提供包含具體洞見的詳細表格分析。"
)
PROMPTS_ZH_TW["EQUATION_ANALYSIS_SYSTEM"] = "你是一位數學專家。請提供詳細的數學分析。"
PROMPTS_ZH_TW["GENERIC_ANALYSIS_SYSTEM"] = (
    "你是一位專注於{content_type}內容的專業分析師。"
)

# Image analysis prompt template
PROMPTS_ZH_TW["vision_prompt"] = """請詳細分析這張圖片，並以以下JSON結構提供回答：

{{
    "detailed_description": "對圖片的全面詳細描述，遵循以下指引：
    - 描述整體構圖與版面配置
    - 識別所有物件、人物、文字與視覺元素
    - 解釋元素之間的關係
    - 注意色彩、光線與視覺風格
    - 描述展示的任何動作或活動
    - 如涉及圖表、圖解等，包含技術細節
    - 始終使用具體名稱而非代詞",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "image",
        "summary": "圖片內容及其重要性的簡明摘要（不超過100字）"
    }}
}}

附加資訊：
- 章節路徑：{section_path}
- 圖片路徑：{image_path}
- 標註：{captions}
- 註腳：{footnotes}

請專注於提供準確、詳細的視覺分析，以便於知識檢索。
請生成語意化的 entity_name；不要返回檔案名或圖號（例如 figure_30_1），除非它們就是正式標題。"""

# Image analysis prompt with context support
PROMPTS_ZH_TW[
    "vision_prompt_with_context"
] = """請結合上下文詳細分析這張圖片，並以以下JSON結構提供回答：

{{
    "detailed_description": "對圖片的全面詳細描述，遵循以下指引：
    - 描述整體構圖與版面配置
    - 識別所有物件、人物、文字與視覺元素
    - 解釋元素之間的關係及其與上下文的聯結
    - 注意色彩、光線與視覺風格
    - 描述展示的任何動作或活動
    - 如涉及圖表、圖解等，包含技術細節
    - 在相關時引用與周圍內容的聯結
    - 始終使用具體名稱而非代詞",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "image",
        "summary": "圖片內容、重要性及與周圍內容關係的簡明摘要（不超過100字）"
    }}
}}

周圍內容上下文：
{context}

文檔結構：
- 章節路徑：{section_path}

圖片詳細資訊：
- 圖片路徑：{image_path}
- 標註：{captions}
- 註腳：{footnotes}

請專注於提供融合上下文的準確、詳細的視覺分析，以便於知識檢索。
請生成語意化的 entity_name；不要返回檔案名或圖號（例如 figure_30_1），除非它們就是正式標題。"""

# Resilient image analysis prompt when raw image file is missing or unreadable
PROMPTS_ZH_TW[
    "vision_fallback_prompt"
] = """請根據以下元數據與上下文詳細分析該圖像內容，並以以下JSON結構提供回答：

{{
    "detailed_description": "基於可用的標題、註腳與周圍上下文對該視覺元素的綜合分析：
    - 綜合說明圖表、圖示、場景或插圖所描繪的內容
    - 解釋元數據中提及的任何文字標籤、數據點或類別
    - 說明各元素之間的關係以及它們與周圍上下文的關聯
    - 始終使用具體名稱而非代詞",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "image",
        "summary": "視覺內容、其重要性以及與周圍內容關係的簡明總結（最多100字）"
    }}
}}

周圍上下文：
{context}

文檔結構：
- 章節路徑：{section_path}

圖像詳情：
- 圖片路徑：{image_path}
- 標註：{captions}
- 註腳：{footnotes}

請專注於提供融合上下文的準確、詳細分析，以便於知識檢索。
使用語意化的entity_name；不要返回檔案名或類似figure_30_1的圖號，除非它們是實際標題。"""

# Image analysis prompt with text fallback
PROMPTS_ZH_TW["text_prompt"] = """根據以下圖片資訊提供分析：

圖片路徑：{image_path}
標註：{captions}
註腳：{footnotes}

{vision_prompt}"""

# Table analysis prompt template
PROMPTS_ZH_TW["table_prompt"] = """請分析此表格內容，並以以下JSON結構提供回答：

{{
    "detailed_description": "對表格的全面分析，包括：
    - 表格結構與組織方式
    - 欄位標題及其含義
    - 關鍵數據點與模式
    - 統計洞見與趨勢
    - 數據元素之間的關係
    - 所呈現數據的重要性
    始终使用具體名稱與數值而非籠統引用。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "table",
        "summary": "表格目的與關鍵發現的簡明摘要（不超過100字）"
    }}
}}

表格資訊：
圖片路徑：{table_img_path}
標題：{table_caption}
內容：{table_body}
註腳：{table_footnote}

請專注於從表格數據中提取有意義的洞見與關聯。"""

# Table analysis prompt with context support
PROMPTS_ZH_TW[
    "table_prompt_with_context"
] = """請結合上下文分析此表格內容，並以以下JSON結構提供回答：

{{
    "detailed_description": "對表格的全面分析，包括：
    - 表格結構與組織方式
    - 欄位標題及其含義
    - 關鍵數據點與模式
    - 統計洞見與趨勢
    - 數據元素之間的關係
    - 所呈現數據與周圍上下文的重要性
    - 表格如何支援或說明周圍內容中的概念
    始终使用具體名稱與數值而非籠統引用。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "table",
        "summary": "表格目的、關鍵發現及與周圍內容關係的簡明摘要（不超過100字）"
    }}
}}

周圍內容上下文：
{context}

表格資訊：
圖片路徑：{table_img_path}
標題：{table_caption}
內容：{table_body}
註腳：{table_footnote}

請專注於在上下文背景下從表格數據中提取有意義的洞見與關聯。"""

# Equation analysis prompt template
PROMPTS_ZH_TW["equation_prompt"] = """請分析此數學公式，並以以下JSON結構提供回答：

{{
    "detailed_description": "對公式的全面分析，包括：
    - 數學含義與解釋
    - 變數及其定義
    - 使用的數學運算與函數
    - 應用領域與背景
    - 物理或理論意義
    - 與其他數學概念的關係
    - 實際應用或用例
    始终使用準確的數學術語。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "equation",
        "summary": "公式目的與重要性的簡明摘要（不超過100字）"
    }}
}}

公式資訊：
公式：{equation_text}
格式：{equation_format}

請專注於提供數學洞見並解釋公式的重要性。"""

# Equation analysis prompt with context support
PROMPTS_ZH_TW[
    "equation_prompt_with_context"
] = """請結合上下文分析此數學公式，並以以下JSON結構提供回答：

{{
    "detailed_description": "對公式的全面分析，包括：
    - 數學含義與解釋
    - 在上下文中變數的定義
    - 使用的數學運算與函數
    - 基於周圍材料的應用領域與背景
    - 物理或理論意義
    - 與上下文中提到的其他數學概念的關係
    - 實際應用或用例
    - 公式如何與更廣泛的討論或架構相關聯
    始终使用準確的數學術語。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "equation",
        "summary": "公式目的、重要性及在上下文中作用的簡明摘要（不超過100字）"
    }}
}}

周圍內容上下文：
{context}

公式資訊：
公式：{equation_text}
格式：{equation_format}

請專注於在更廣泛的上下文中提供數學洞見並解釋公式的重要性。"""

# Generic content analysis prompt template
PROMPTS_ZH_TW[
    "generic_prompt"
] = """請分析此{content_type}內容，並以以下JSON結構提供回答：

{{
    "detailed_description": "對內容的全面分析，包括：
    - 內容結構與組織
    - 關鍵資訊與元素
    - 元件之間的關係
    - 背景與重要性
    - 與知識檢索相關的細節
    始终使用適合{content_type}內容的專業術語。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "{content_type}",
        "summary": "內容目的與要點的簡明摘要（不超過100字）"
    }}
}}

內容：{content}

請專注於提取對知識檢索有用的實質資訊。"""

# Generic content analysis prompt with context support
PROMPTS_ZH_TW[
    "generic_prompt_with_context"
] = """請結合上下文分析此{content_type}內容，並以以下JSON結構提供回答：

{{
    "detailed_description": "對內容的全面分析，包括：
    - 內容結構與組織
    - 關鍵資訊與元素
    - 元件之間的關係
    - 與周圍內容相關的背景與重要性
    - 此內容如何與更廣泛的討論相聯結或支援
    - 與知識檢索相關的細節
    始终使用適合{content_type}內容的專業術語。",
    "entity_info": {{
        "entity_name": "{entity_name}",
        "entity_type": "{content_type}",
        "summary": "內容目的、要點及與周圍上下文關係的簡明摘要（不超過100字）"
    }}
}}

周圍內容上下文：
{context}

內容：{content}

請專注於提取對知識檢索有用的資訊，並理解內容在更廣泛上下文中的作用。"""

# Modal chunk templates
PROMPTS_ZH_TW["image_chunk"] = """
圖片內容分析：
- 章節路徑：{section_path}
- 鄰近文字：{neighbor_text}
圖片路徑：{image_path}
標註：{captions}
註腳：{footnotes}

視覺分析：{enhanced_caption}"""

PROMPTS_ZH_TW["table_chunk"] = """表格分析：
圖片路徑：{table_img_path}
標題：{table_caption}
結構：{table_body}
註腳：{table_footnote}

分析：{enhanced_caption}"""

PROMPTS_ZH_TW["equation_chunk"] = """數學公式分析：
公式：{equation_text}
格式：{equation_format}

數學分析：{enhanced_caption}"""

PROMPTS_ZH_TW["generic_chunk"] = """{content_type}內容分析：
內容：{content}

分析：{enhanced_caption}"""

# Query-related prompts
PROMPTS_ZH_TW["QUERY_IMAGE_DESCRIPTION"] = (
    "請簡要描述這張圖片的主要內容、關鍵元素與重要資訊。"
)

PROMPTS_ZH_TW["QUERY_IMAGE_ANALYST_SYSTEM"] = (
    "你是一位能準確描述圖片內容的專業圖像分析師。"
)

PROMPTS_ZH_TW[
    "QUERY_TABLE_ANALYSIS"
] = """請分析以下表格數據的主要內容、結構與關鍵資訊：

表格數據：
{table_data}

表格標題：{table_caption}

請簡要總結表格的主要內容、數據特徵與重要發現。"""

PROMPTS_ZH_TW["QUERY_TABLE_ANALYST_SYSTEM"] = (
    "你是一位能準確分析表格數據的專業資料分析師。"
)

PROMPTS_ZH_TW["QUERY_EQUATION_ANALYSIS"] = """請解釋以下數學公式的含義與用途：

LaTeX公式：{latex}
公式標題：{equation_caption}

請簡要說明這個公式的數學意義、應用場景與重要性。"""

PROMPTS_ZH_TW["QUERY_EQUATION_ANALYST_SYSTEM"] = (
    "你是一位能清晰解釋數學公式的數學專家。"
)

PROMPTS_ZH_TW[
    "QUERY_GENERIC_ANALYSIS"
] = """請分析以下{content_type}類型內容並提取其主要資訊與關鍵特徵：

內容：{content_str}

請簡要總結此內容的主要特徵與重要資訊。"""

PROMPTS_ZH_TW["QUERY_GENERIC_ANALYST_SYSTEM"] = (
    "你是一位能準確分析{content_type}類型內容的專業內容分析師。"
)

PROMPTS_ZH_TW["QUERY_ENHANCEMENT_SUFFIX"] = (
    "\n\n請基於使用者查詢與提供的多模態內容資訊，提供全面的回答。"
)

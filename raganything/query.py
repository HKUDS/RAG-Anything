"""
Query functionality for RAGAnything

Contains all query-related methods for both text and multimodal queries
"""

import json
import hashlib
import re
from typing import Dict, List, Any
from pathlib import Path
from lightrag import QueryParam
from lightrag.utils import always_get_an_event_loop
from raganything.prompt import PROMPTS
from raganything.utils import (
    get_processor_for_type,
    encode_image_to_base64,
    validate_image_file,
)


def _extract_page_info(query: str) -> dict:
    """
    第一阶段：纯正则快速提取页码信息。

    支持的模式（中英文）：
      - 单页:  "第3页", "page 3", "p.3", "p3"
      - 范围:  "第3-5页", "pages 3-5", "3到5页", "3 to 5"
      - 多页:  "第3页和第7页", "pages 3, 7"
      - 周围:  "第3页左右", "around page 3", "第3页附近"

    Returns:
        {
            "has_page_constraint": bool,
            "pages": list[int],           # 所有明确提及的页码（含范围展开）
            "page_range": (int,int)|None, # 若为连续范围则记录首尾
            "context_radius": int,        # 建议向外扩展几页（模糊词时=2，否则=1）
            "raw_mention": str,           # 原始匹配文本
            "source": str,               # "regex" 或 "llm"
        }
    """
    result = {
        "has_page_constraint": False,
        "pages": [],
        "page_range": None,
        "context_radius": 1,
        "raw_mention": "",
        "source": "regex",
    }

    # ── 模式 1：范围  "第3-5页" / "pages 3-5" / "3到5页" / "3 to 5页"
    range_pattern = re.compile(
        r"(?:第\s*(\d+)\s*[-到~至]\s*(\d+)\s*页"
        r"|[Pp]ages?\s+(\d+)\s*[-–to]\s*(\d+)"
        r"|(\d+)\s*[-到~至]\s*(\d+)\s*页)",
        re.IGNORECASE,
    )
    m = range_pattern.search(query)
    if m:
        groups = [g for g in m.groups() if g is not None]
        start, end = int(groups[0]), int(groups[1])
        if start > end:
            start, end = end, start
        result["has_page_constraint"] = True
        result["pages"] = list(range(start, end + 1))
        result["page_range"] = (start, end)
        result["raw_mention"] = m.group(0)
        if re.search(r"左右|附近|around|about|approximately", query, re.IGNORECASE):
            result["context_radius"] = 2
        return result

    # ── 模式 2：多页列举  "第3页和第7页" / "pages 3, 7, 10"
    multi_pattern = re.compile(
        r"(?:第\s*\d+\s*页(?:\s*[和,、及]\s*第\s*\d+\s*页)+)"
        r"|(?:[Pp]ages?\s+\d+(?:\s*[,和]\s*\d+)+)",
        re.IGNORECASE,
    )
    m = multi_pattern.search(query)
    if m:
        nums = list(map(int, re.findall(r"\d+", m.group(0))))
        result["has_page_constraint"] = True
        result["pages"] = sorted(set(nums))
        result["raw_mention"] = m.group(0)
        return result

    # ── 模式 3：单页  "第3页" / "page 3" / "p.3" / "p3"
    single_pattern = re.compile(
        r"第\s*(\d+)\s*页"
        r"|[Pp]age\s+(\d+)"
        r"|[Pp]\.?\s*(\d+)(?=\D|$)",
        re.IGNORECASE,
    )
    m = single_pattern.search(query)
    if m:
        num = int(next(g for g in m.groups() if g is not None))
        result["has_page_constraint"] = True
        result["pages"] = [num]
        result["page_range"] = (num, num)
        result["raw_mention"] = m.group(0)
        if re.search(r"左右|附近|around|about|approximately", query, re.IGNORECASE):
            result["context_radius"] = 2
        return result

    return result


# LLM 兜底用的 prompt（保持极简，减少 token 消耗）
_PAGE_EXTRACTION_SYSTEM = (
    "You are a precise information extractor. "
    "Always respond with valid JSON only, no explanation."
)

_PAGE_EXTRACTION_PROMPT = """\
Does the following user query explicitly RESTRICT the answer to specific page(s) of a document?

CRITICAL DISTINCTION:
- "限制到某页" (page constraint = TRUE): User wants the answer to focus ON specific pages.
  e.g. "第8页中是否包含折线图", "分析第3-5页的内容", "第9页附近的表格"
- "询问是哪页" (page constraint = FALSE): User is ASKING which page something appears on.
  e.g. "哪一页首次出现了...", "which page shows...", "在哪页能找到...", "首次出现在第几页"

Query: {query}

Respond with JSON in this exact format:
{{
  "has_page_constraint": true or false,
  "pages": [list of integers, empty if none],
  "page_range": [start, end] or null,
  "context_radius": 1 or 2,
  "raw_mention": "the exact phrase that mentions pages, or empty string"
}}

Rules:
- "has_page_constraint": true ONLY if the user is limiting scope to specific pages they already know
- If the query contains "哪一页/哪页/which page/what page/首次出现/first appears", it is ALWAYS false
- "pages": all page numbers mentioned (expand ranges, e.g. 3-5 → [3,4,5])
- "page_range": [start, end] only for contiguous ranges, otherwise null
- "context_radius": 2 if query uses vague words like "around/about/附近/左右", else 1
- "raw_mention": copy the exact page-related phrase, or empty string if has_page_constraint is false

Examples:
  "第8页中是否包含折线图？" → {{"has_page_constraint": true, "pages": [8], "page_range": [8,8], "context_radius": 1, "raw_mention": "第8页"}}
  "第9页附近的表格" → {{"has_page_constraint": true, "pages": [9], "page_range": [9,9], "context_radius": 2, "raw_mention": "第9页附近"}}
  "文章快结尾那几页讲了什么" → {{"has_page_constraint": true, "pages": [19,20], "page_range": [19,20], "context_radius": 2, "raw_mention": "快结尾那几页"}}
  "哪一页首次出现了折线图？" → {{"has_page_constraint": false, "pages": [], "page_range": null, "context_radius": 1, "raw_mention": ""}}
  "test4.pdf 中哪一页首次出现了 DocBench Accuracy 随 Page Range 变化的折线图？" → {{"has_page_constraint": false, "pages": [], "page_range": null, "context_radius": 1, "raw_mention": ""}}
  "which page shows the accuracy chart?" → {{"has_page_constraint": false, "pages": [], "page_range": null, "context_radius": 1, "raw_mention": ""}}
  "What is machine learning?" → {{"has_page_constraint": false, "pages": [], "page_range": null, "context_radius": 1, "raw_mention": ""}}
"""


async def _extract_page_info_with_llm_fallback(
    query: str,
    llm_func,
    logger=None,
) -> dict:
    """
    两阶段页码提取：正则优先，失败时调用 LLM 兜底。

    Args:
        query:    用户原始 query
        llm_func: RAGAnything 的 self.llm_model_func，签名为
                  llm_func(prompt, system_prompt=None, ...) -> str
        logger:   可选 logger

    Returns:
        与 _extract_page_info() 相同结构的 dict，额外包含 "source" 字段
        ("regex" | "llm" | "llm_failed")
    """
    # ── 第一阶段：正则 ──
    result = _extract_page_info(query)
    if result["has_page_constraint"]:
        if logger:
            logger.debug(f"[PageExtract] regex hit: {result['raw_mention']!r}")
        return result

    # ── 第二阶段：LLM 兜底 ──
    if logger:
        logger.debug("[PageExtract] regex miss, falling back to LLM")

    try:
        prompt = _PAGE_EXTRACTION_PROMPT.format(query=query)
        raw = await llm_func(prompt, system_prompt=_PAGE_EXTRACTION_SYSTEM)

        # 清理 LLM 可能返回的 markdown 代码块
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
        parsed = json.loads(raw)

        # 校验并标准化返回值
        pages = [int(p) for p in parsed.get("pages", []) if str(p).isdigit()]
        page_range_raw = parsed.get("page_range")
        page_range = None
        if isinstance(page_range_raw, list) and len(page_range_raw) == 2:
            page_range = (int(page_range_raw[0]), int(page_range_raw[1]))
        elif page_range_raw is None and len(pages) > 0:
            # 如果 LLM 没给 page_range 但只有一页，自动补全
            if len(pages) == 1:
                page_range = (pages[0], pages[0])

        llm_result = {
            "has_page_constraint": bool(parsed.get("has_page_constraint", False)),
            "pages": sorted(set(pages)),
            "page_range": page_range,
            "context_radius": int(parsed.get("context_radius", 1)),
            "raw_mention": str(parsed.get("raw_mention", "")),
            "source": "llm",
        }

        # 防御：has_page_constraint=True 但 pages 为空是矛盾状态，强制纠正
        if llm_result["has_page_constraint"] and not llm_result["pages"]:
            llm_result["has_page_constraint"] = False
            llm_result["raw_mention"] = ""
            if logger:
                logger.warning(
                    "[PageExtract] LLM returned has_constraint=True with empty pages, corrected to False"
                )

        if logger:
            logger.info(
                f"[PageExtract] LLM result: has_constraint={llm_result['has_page_constraint']}, "
                f"pages={llm_result['pages']}, mention={llm_result['raw_mention']!r}"
            )
        return llm_result

    except Exception as e:
        if logger:
            logger.warning(f"[PageExtract] LLM fallback failed ({e}), treating as no constraint")
        # 兜底失败：不阻断主流程，当作无页码约束处理
        result["source"] = "llm_failed"
        return result


def _build_page_aware_system_prompt(
    page_info: dict,
    base_system_prompt: str | None = None,
) -> str:
    """
    根据提取到的页码信息，生成带页码权重约束的 system prompt。
    """
    if not page_info["has_page_constraint"]:
        return base_system_prompt or ""

    pages = page_info["pages"]
    if not pages:
        # has_page_constraint=True 但 pages 为空（LLM 返回不一致），安全降级
        return base_system_prompt or ""

    radius = page_info["context_radius"]

    # 计算扩展后的关注区间
    lo = max(1, min(pages) - radius)
    hi = max(pages) + radius

    page_instruction = (
        f"\n\n## Page-Focused Answering Instruction\n"
        f"The user's question specifically concerns page(s): {pages}.\n"
        f"When answering:\n"
        f"1. **Primary source**: Prioritize content from pages {lo}–{hi} "
        f"(target page(s) ± {radius} page context window).\n"
        f"2. **Secondary source**: You may reference content from other pages "
        f"only when it directly supports or clarifies the primary content.\n"
        f"3. If the primary pages do not contain sufficient information, "
        f"explicitly state this before drawing from other pages.\n"
        f"4. **If no content from page(s) {pages} is present in the context at all, "
        f"you MUST explicitly state that the page does not exist or is out of range in this document. "
        f"Do NOT fabricate or infer content for pages not present in the context.**\n"
        f"5. Always cite which page each piece of information comes from.\n"
    )

    if base_system_prompt:
        return base_system_prompt + page_instruction
    return page_instruction.strip()


async def _fetch_page_chunks(
    page_info: dict,
    doc_status_storage,
    text_chunks_storage,
    file_path: str | None = None,
    logger=None,
) -> tuple[list[dict], bool | None]:
    """
    从存储中直接查出目标页的所有 chunk。

    流程：
      1. 从 doc_status 的底层 KV 存储拿到 chunks_list
         （RAGAnything 在 processor.py 里以原始 dict 形式存入，绕过 DocProcessingStatus dataclass）
      2. get_by_ids 批量读出 chunk 数据
      3. 按 page_idx 筛出目标页 ± radius 的 chunk

    Args:
        page_info:            _extract_page_info() 的返回值
        doc_status_storage:   self.lightrag.doc_status
        text_chunks_storage:  self.lightrag.text_chunks
        file_path:            文档文件名（用于 get_doc_by_file_path 反查，可选）
        logger:               可选 logger

    Returns:
        tuple[list[dict], bool | None]:
            True  = 找到目标页 chunk
            False = 元数据齐全但目标页确实不存在
            None  = 无法判断（存储访问失败或无 page_idx 元数据）
    """
    pages = page_info["pages"]
    radius = page_info["context_radius"]
    lo = max(1, min(pages) - radius)
    hi = max(pages) + radius
    target_set = set(range(lo, hi + 1))

    try:
        # ── Step 1：拿到所有 chunk ID ──
        # RAGAnything 的 chunks_list 存在 doc_status 的底层 dict 里，
        # 用 get_by_id 直接按 doc_id 读原始数据。
        # 但查询时不知道 doc_id，所以直接对 text_chunks 的所有 key 操作。
        # text_chunks 存储提供 filter_keys(set) 接口，传空 set 可拿所有 key。
        all_chunk_ids: list[str] = []
        try:
            # filter_keys 传入空集合返回所有已存在的 key
            existing_keys = await text_chunks_storage.filter_keys(set())
            # filter_keys 返回的是"不存在"的 key，所以要反向：传全集取补集
            # 实际上直接用一个已知不存在的大集合来触发"返回存在的 key"并不可靠
            # 改用 json_kv_impl 的底层：直接读存储文件
            raise NotImplementedError("filter_keys semantics unclear, using fallback")
        except Exception:
            pass

        # fallback：从 doc_status 原始 KV 读 chunks_list
        # doc_status 的 get_by_id 返回原始 dict（包含 RAGAnything 写入的 chunks_list）
        if not all_chunk_ids and file_path:
            try:
                # get_doc_by_file_path 可能返回 dataclass 或 dict，都处理
                raw = await doc_status_storage.get_doc_by_file_path(file_path)
                if raw is not None:
                    if isinstance(raw, dict):
                        all_chunk_ids = raw.get("chunks_list", []) or []
                    elif hasattr(raw, "__dict__"):
                        all_chunk_ids = getattr(raw, "chunks_list", None) or []
            except Exception as e:
                if logger:
                    logger.debug(f"[PageFetch] get_doc_by_file_path failed: {e}")

        if not all_chunk_ids:
            # 最后 fallback：遍历 doc_status，用 get_by_id 读原始 dict
            try:
                docs_page, total = await doc_status_storage.get_docs_paginated(
                    status_filter=None, page=1, page_size=200
                )
                for doc_id, _doc_obj in docs_page:
                    # get_by_id 返回底层原始 dict，包含 RAGAnything 自定义字段
                    raw_doc = await doc_status_storage.get_by_id(doc_id)
                    if isinstance(raw_doc, dict):
                        all_chunk_ids.extend(raw_doc.get("chunks_list", []) or [])
            except Exception as e:
                if logger:
                    logger.warning(f"[PageFetch] doc_status iteration failed: {e}")

        if not all_chunk_ids:
            if logger:
                logger.warning("[PageFetch] Could not retrieve any chunk IDs")
            return [], None

        if logger:
            logger.debug(f"[PageFetch] Got {len(all_chunk_ids)} chunk IDs to scan")

        # ── Step 2：批量读取 chunk 数据 ──
        records = await text_chunks_storage.get_by_ids(all_chunk_ids)

        # ── Step 3：按 page_idx 过滤 ──
        has_page_idx_metadata = False
        target_chunks = []

        for record in records:
            if record is None:
                continue
            raw_page = record.get("page_idx")
            if raw_page is not None:
                has_page_idx_metadata = True
                page_1based = int(raw_page) + 1  # 0-based → 1-based
                if page_1based in target_set:
                    target_chunks.append(record)

        if not has_page_idx_metadata:
            if logger:
                logger.warning("[PageFetch] No page_idx metadata — document may need reprocessing")
            return [], None

        if logger:
            logger.info(
                f"[PageFetch] pages {lo}–{hi}: found {len(target_chunks)} chunks "
                f"out of {len(all_chunk_ids)} total"
            )

        return target_chunks, len(target_chunks) > 0

    except Exception as e:
        if logger:
            logger.warning(f"[PageFetch] Failed: {e}")
        return [], None


class QueryMixin:
    """QueryMixin class containing query functionality for RAGAnything"""

    def _generate_multimodal_cache_key(
        self, query: str, multimodal_content: List[Dict[str, Any]], mode: str, **kwargs
    ) -> str:
        """
        Generate cache key for multimodal query

        Args:
            query: Base query text
            multimodal_content: List of multimodal content
            mode: Query mode
            **kwargs: Additional parameters

        Returns:
            str: Cache key hash
        """
        # Create a normalized representation of the query parameters
        cache_data = {
            "query": query.strip(),
            "mode": mode,
        }

        # Normalize multimodal content for stable caching
        normalized_content = []
        if multimodal_content:
            for item in multimodal_content:
                if isinstance(item, dict):
                    normalized_item = {}
                    for key, value in item.items():
                        # For file paths, use basename to make cache more portable
                        if key in [
                            "img_path",
                            "image_path",
                            "file_path",
                        ] and isinstance(value, str):
                            normalized_item[key] = Path(value).name
                        # For large content, create a hash instead of storing directly
                        elif (
                            key in ["table_data", "table_body"]
                            and isinstance(value, str)
                            and len(value) > 200
                        ):
                            normalized_item[f"{key}_hash"] = hashlib.md5(
                                value.encode()
                            ).hexdigest()
                        else:
                            normalized_item[key] = value
                    normalized_content.append(normalized_item)
                else:
                    normalized_content.append(item)

        cache_data["multimodal_content"] = normalized_content

        # Add relevant kwargs to cache data
        relevant_kwargs = {
            k: v
            for k, v in kwargs.items()
            if k
            in [
                "stream",
                "response_type",
                "top_k",
                "max_tokens",
                "temperature",
                # "only_need_context",
                # "only_need_prompt",
            ]
        }
        cache_data.update(relevant_kwargs)

        # Generate hash from the cache data
        cache_str = json.dumps(cache_data, sort_keys=True, ensure_ascii=False)
        cache_hash = hashlib.md5(cache_str.encode()).hexdigest()

        return f"multimodal_query:{cache_hash}"

    async def aquery(
        self, query: str, mode: str = "mix", system_prompt: str | None = None, **kwargs
    ) -> str:
        """
        Pure text query - directly calls LightRAG's query functionality

        Args:
            query: Query text
            mode: Query mode ("local", "global", "hybrid", "naive", "mix", "bypass")
            system_prompt: Optional system prompt to include.
            **kwargs: Other query parameters, will be passed to QueryParam
                - vlm_enhanced: bool, default True when vision_model_func is available.
                  If True, will parse image paths in retrieved context and replace them
                  with base64 encoded images for VLM processing.

        Returns:
            str: Query result
        """
        if self.lightrag is None:
            raise ValueError(
                "No LightRAG instance available. Please process documents first or provide a pre-initialized LightRAG instance."
            )

        # ── 页码感知：正则优先，失败时 LLM 兜底 ──
        page_info = await _extract_page_info_with_llm_fallback(
            query, self.llm_model_func, self.logger
        )
        if page_info["has_page_constraint"]:
            self.logger.info(
                f"Page constraint detected [{page_info['source']}]: "
                f"pages={page_info['pages']}, mention='{page_info['raw_mention']}'"
            )
            system_prompt = _build_page_aware_system_prompt(page_info, system_prompt)

        # Check if VLM enhanced query should be used
        vlm_enhanced = kwargs.pop("vlm_enhanced", None)

        # Auto-determine VLM enhanced based on availability
        if vlm_enhanced is None:
            vlm_enhanced = (
                hasattr(self, "vision_model_func")
                and self.vision_model_func is not None
            )

        # Use VLM enhanced query if enabled and available
        if (
            vlm_enhanced
            and hasattr(self, "vision_model_func")
            and self.vision_model_func
        ):
            return await self.aquery_vlm_enhanced(
                query, mode=mode, system_prompt=system_prompt, **kwargs
            )
        elif vlm_enhanced and (
            not hasattr(self, "vision_model_func") or not self.vision_model_func
        ):
            self.logger.warning(
                "VLM enhanced query requested but vision_model_func is not available, falling back to normal query"
            )

        # Create query parameters
        query_param = QueryParam(mode=mode, **kwargs)

        self.logger.info(f"Executing text query: {query[:100]}...")
        self.logger.info(f"Query mode: {mode}")

        # Call LightRAG's query method
        result = await self.lightrag.aquery(
            query, param=query_param, system_prompt=system_prompt
        )

        self.logger.info("Text query completed")
        return result

    async def aquery_with_multimodal(
        self,
        query: str,
        multimodal_content: List[Dict[str, Any]] = None,
        mode: str = "mix",
        **kwargs,
    ) -> str:
        """
        Multimodal query - combines text and multimodal content for querying

        Args:
            query: Base query text
            multimodal_content: List of multimodal content, each element contains:
                - type: Content type ("image", "table", "equation", etc.)
                - Other fields depend on type (e.g., img_path, table_data, latex, etc.)
            mode: Query mode ("local", "global", "hybrid", "naive", "mix", "bypass")
            **kwargs: Other query parameters, will be passed to QueryParam

        Returns:
            str: Query result

        Examples:
            # Pure text query
            result = await rag.query_with_multimodal("What is machine learning?")

            # Image query
            result = await rag.query_with_multimodal(
                "Analyze the content in this image",
                multimodal_content=[{
                    "type": "image",
                    "img_path": "./image.jpg"
                }]
            )

            # Table query
            result = await rag.query_with_multimodal(
                "Analyze the data trends in this table",
                multimodal_content=[{
                    "type": "table",
                    "table_data": "Name,Age\nAlice,25\nBob,30"
                }]
            )
        """
        # Ensure LightRAG is initialized
        await self._ensure_lightrag_initialized()

        self.logger.info(f"Executing multimodal query: {query[:100]}...")
        self.logger.info(f"Query mode: {mode}")

        # If no multimodal content, fallback to pure text query
        if not multimodal_content:
            self.logger.info("No multimodal content provided, executing text query")
            return await self.aquery(query, mode=mode, **kwargs)

        # Generate cache key for multimodal query
        cache_key = self._generate_multimodal_cache_key(
            query, multimodal_content, mode, **kwargs
        )

        # Check cache if available and enabled
        cached_result = None
        if (
            hasattr(self, "lightrag")
            and self.lightrag
            and hasattr(self.lightrag, "llm_response_cache")
            and self.lightrag.llm_response_cache
        ):
            if self.lightrag.llm_response_cache.global_config.get(
                "enable_llm_cache", True
            ):
                try:
                    cached_result = await self.lightrag.llm_response_cache.get_by_id(
                        cache_key
                    )
                    if cached_result and isinstance(cached_result, dict):
                        result_content = cached_result.get("return")
                        if result_content:
                            self.logger.info(
                                f"Multimodal query cache hit: {cache_key[:16]}..."
                            )
                            return result_content
                except Exception as e:
                    self.logger.debug(f"Error accessing multimodal query cache: {e}")

        # Process multimodal content to generate enhanced query text
        enhanced_query = await self._process_multimodal_query_content(
            query, multimodal_content
        )

        self.logger.info(
            f"Generated enhanced query length: {len(enhanced_query)} characters"
        )

        # Execute enhanced query
        result = await self.aquery(enhanced_query, mode=mode, **kwargs)

        # Save to cache if available and enabled
        if (
            hasattr(self, "lightrag")
            and self.lightrag
            and hasattr(self.lightrag, "llm_response_cache")
            and self.lightrag.llm_response_cache
        ):
            if self.lightrag.llm_response_cache.global_config.get(
                "enable_llm_cache", True
            ):
                try:
                    # Create cache entry for multimodal query
                    cache_entry = {
                        "return": result,
                        "cache_type": "multimodal_query",
                        "original_query": query,
                        "multimodal_content_count": len(multimodal_content),
                        "mode": mode,
                    }

                    await self.lightrag.llm_response_cache.upsert(
                        {cache_key: cache_entry}
                    )
                    self.logger.info(
                        f"Saved multimodal query result to cache: {cache_key[:16]}..."
                    )
                except Exception as e:
                    self.logger.debug(f"Error saving multimodal query to cache: {e}")

        # Ensure cache is persisted to disk
        if (
            hasattr(self, "lightrag")
            and self.lightrag
            and hasattr(self.lightrag, "llm_response_cache")
            and self.lightrag.llm_response_cache
        ):
            try:
                await self.lightrag.llm_response_cache.index_done_callback()
            except Exception as e:
                self.logger.debug(f"Error persisting multimodal query cache: {e}")

        self.logger.info("Multimodal query completed")
        return result

    async def aquery_vlm_enhanced(
        self, query: str, mode: str = "mix", system_prompt: str | None = None, **kwargs
    ) -> str:
        """
        VLM enhanced query - replaces image paths in retrieved context with base64 encoded images for VLM processing

        Args:
            query: User query
            mode: Underlying LightRAG query mode
            system_prompt: Optional system prompt to include
            **kwargs: Other query parameters

        Returns:
            str: VLM query result
        """
        # Ensure VLM is available
        if not hasattr(self, "vision_model_func") or not self.vision_model_func:
            raise ValueError(
                "VLM enhanced query requires vision_model_func. "
                "Please provide a vision model function when initializing RAGAnything."
            )

        # Ensure LightRAG is initialized
        await self._ensure_lightrag_initialized()

        self.logger.info(f"Executing VLM enhanced query: {query[:100]}...")

        # ── 页码感知：正则优先，失败时 LLM 兜底 ──
        page_info = await _extract_page_info_with_llm_fallback(
            query, self.llm_model_func, self.logger
        )
        if page_info["has_page_constraint"]:
            self.logger.info(
                f"[VLM] Page constraint [{page_info['source']}]: "
                f"pages={page_info['pages']}, radius={page_info['context_radius']}"
            )
            system_prompt = _build_page_aware_system_prompt(page_info, system_prompt)

        # Clear previous image cache
        if hasattr(self, "_current_images_base64"):
            delattr(self, "_current_images_base64")

        # 1. Get original retrieval prompt (without generating final answer)
        query_param = QueryParam(mode=mode, only_need_prompt=True, **kwargs)
        raw_prompt = await self.lightrag.aquery(query, param=query_param)

        self.logger.debug("Retrieved raw prompt from LightRAG")

        # ── 页码感知：直接从存储查出目标页 chunk，注入到 prompt ──
        page_chunks: list[dict] = []
        if page_info["has_page_constraint"]:
            # 尝试从 query 中提取文件名（如 "test4.pdf 第8页..."）
            _file_hint = None
            _file_match = re.search(r'[\w\-\.]+\.pdf', query, re.IGNORECASE)
            if _file_match:
                _file_hint = _file_match.group(0)

            page_chunks, primary_hit = await _fetch_page_chunks(
                page_info,
                doc_status_storage=self.lightrag.doc_status,
                text_chunks_storage=self.lightrag.text_chunks,
                file_path=_file_hint,
                logger=self.logger,
            )

            if primary_hit is False:
                pages = page_info["pages"]
                msg = (
                    f"文档中未找到第 {pages} 页的相关内容。"
                    f"该页码可能超出文档范围，或该页不包含可检索的内容。"
                    f"请确认页码是否正确。"
                ) if any('\u4e00' <= c <= '\u9fff' for c in query) else (
                    f"No content found for page(s) {pages} in the document. "
                    f"The page number may be out of range, or the page contains no retrievable content. "
                    f"Please verify the page number."
                )
                self.logger.info(f"[VLM] Page {pages} not found in document, returning early")
                return msg
            elif primary_hit is None:
                self.logger.info("[VLM] No page_idx metadata, proceeding without page injection")
            else:
                self.logger.info(f"[VLM] Injecting {len(page_chunks)} chunks from target pages into prompt")

        # 2. Extract and process image paths
        enhanced_prompt, images_found = await self._process_image_paths_for_vlm(
            raw_prompt
        )

        # ── 把目标页 chunk 内容注入到 prompt 最前面 ──
        if page_chunks:
            pages = page_info["pages"]
            radius = page_info["context_radius"]
            lo = max(1, min(pages) - radius)
            hi = max(pages) + radius
            injected = (
                f"[DIRECT PAGE CONTENT — pages {lo}–{hi}, highest priority]\n"
                + "\n---\n".join(
                    c.get("content", "") for c in page_chunks if c.get("content")
                )
                + "\n[END DIRECT PAGE CONTENT]\n\n"
            )
            enhanced_prompt = injected + enhanced_prompt

        if not images_found:
            self.logger.info("No valid images found, falling back to normal query")
            query_param = QueryParam(mode=mode, **kwargs)
            # 有目标页 chunk 时，把内容拼入 query 让 LLM 参考
            if page_chunks:
                pages = page_info["pages"]
                radius = page_info["context_radius"]
                lo = max(1, min(pages) - radius)
                hi = max(pages) + radius
                page_content = "\n---\n".join(
                    c.get("content", "") for c in page_chunks if c.get("content")
                )
                augmented_query = (
                    f"[Reference content from pages {lo}–{hi}]\n{page_content}\n"
                    f"[End reference content]\n\n{query}"
                )
                return await self.lightrag.aquery(
                    augmented_query, param=query_param, system_prompt=system_prompt
                )
            return await self.lightrag.aquery(
                query, param=query_param, system_prompt=system_prompt
            )

        self.logger.info(f"Processed {images_found} images for VLM")

        # 3. Build VLM message format
        messages = self._build_vlm_messages_with_images(
            enhanced_prompt, query, system_prompt
        )

        # 4. Call VLM for question answering
        result = await self._call_vlm_with_multimodal_content(messages)

        self.logger.info("VLM enhanced query completed")
        return result

    async def _process_multimodal_query_content(
        self, base_query: str, multimodal_content: List[Dict[str, Any]]
    ) -> str:
        """
        Process multimodal query content to generate enhanced query text

        Args:
            base_query: Base query text
            multimodal_content: List of multimodal content

        Returns:
            str: Enhanced query text
        """
        self.logger.info("Starting multimodal query content processing...")

        enhanced_parts = [f"User query: {base_query}"]

        for i, content in enumerate(multimodal_content):
            content_type = content.get("type", "unknown")
            self.logger.info(
                f"Processing {i+1}/{len(multimodal_content)} multimodal content: {content_type}"
            )

            try:
                # Get appropriate processor
                processor = get_processor_for_type(self.modal_processors, content_type)

                if processor:
                    # Generate content description
                    description = await self._generate_query_content_description(
                        processor, content, content_type
                    )
                    enhanced_parts.append(
                        f"\nRelated {content_type} content: {description}"
                    )
                else:
                    # If no appropriate processor, use basic description
                    basic_desc = str(content)[:200]
                    enhanced_parts.append(
                        f"\nRelated {content_type} content: {basic_desc}"
                    )

            except Exception as e:
                self.logger.error(f"Error processing multimodal content: {str(e)}")
                # Continue processing other content
                continue

        enhanced_query = "\n".join(enhanced_parts)
        enhanced_query += PROMPTS["QUERY_ENHANCEMENT_SUFFIX"]

        self.logger.info("Multimodal query content processing completed")
        return enhanced_query

    async def _generate_query_content_description(
        self, processor, content: Dict[str, Any], content_type: str
    ) -> str:
        """
        Generate content description for query

        Args:
            processor: Multimodal processor
            content: Content data
            content_type: Content type

        Returns:
            str: Content description
        """
        try:
            if content_type == "image":
                return await self._describe_image_for_query(processor, content)
            elif content_type == "table":
                return await self._describe_table_for_query(processor, content)
            elif content_type == "equation":
                return await self._describe_equation_for_query(processor, content)
            else:
                return await self._describe_generic_for_query(
                    processor, content, content_type
                )

        except Exception as e:
            self.logger.error(f"Error generating {content_type} description: {str(e)}")
            return f"{content_type} content: {str(content)[:100]}"

    async def _describe_image_for_query(
        self, processor, content: Dict[str, Any]
    ) -> str:
        """Generate image description for query"""
        image_path = content.get("img_path")
        captions = content.get("image_caption", content.get("img_caption", []))
        footnotes = content.get("image_footnote", content.get("img_footnote", []))

        if image_path and Path(image_path).exists():
            # If image exists, use vision model to generate description
            image_base64 = processor._encode_image_to_base64(image_path)
            if image_base64:
                prompt = PROMPTS["QUERY_IMAGE_DESCRIPTION"]
                description = await processor.modal_caption_func(
                    prompt,
                    image_data=image_base64,
                    system_prompt=PROMPTS["QUERY_IMAGE_ANALYST_SYSTEM"],
                )
                return description

        # If image doesn't exist or processing failed, use existing information
        parts = []
        if image_path:
            parts.append(f"Image path: {image_path}")
        if captions:
            parts.append(f"Image captions: {', '.join(captions)}")
        if footnotes:
            parts.append(f"Image footnotes: {', '.join(footnotes)}")

        return "; ".join(parts) if parts else "Image content information incomplete"

    async def _describe_table_for_query(
        self, processor, content: Dict[str, Any]
    ) -> str:
        """Generate table description for query"""
        table_data = content.get("table_data", "")
        table_caption = content.get("table_caption", "")

        prompt = PROMPTS["QUERY_TABLE_ANALYSIS"].format(
            table_data=table_data, table_caption=table_caption
        )

        description = await processor.modal_caption_func(
            prompt, system_prompt=PROMPTS["QUERY_TABLE_ANALYST_SYSTEM"]
        )

        return description

    async def _describe_equation_for_query(
        self, processor, content: Dict[str, Any]
    ) -> str:
        """Generate equation description for query"""
        latex = content.get("latex", "")
        equation_caption = content.get("equation_caption", "")

        prompt = PROMPTS["QUERY_EQUATION_ANALYSIS"].format(
            latex=latex, equation_caption=equation_caption
        )

        description = await processor.modal_caption_func(
            prompt, system_prompt=PROMPTS["QUERY_EQUATION_ANALYST_SYSTEM"]
        )

        return description

    async def _describe_generic_for_query(
        self, processor, content: Dict[str, Any], content_type: str
    ) -> str:
        """Generate generic content description for query"""
        content_str = str(content)

        prompt = PROMPTS["QUERY_GENERIC_ANALYSIS"].format(
            content_type=content_type, content_str=content_str
        )

        description = await processor.modal_caption_func(
            prompt,
            system_prompt=PROMPTS["QUERY_GENERIC_ANALYST_SYSTEM"].format(
                content_type=content_type
            ),
        )

        return description

    async def _process_image_paths_for_vlm(self, prompt: str) -> tuple[str, int]:
        """
        Process image paths in prompt, keeping original paths and adding VLM markers

        Args:
            prompt: Original prompt

        Returns:
            tuple: (processed prompt, image count)
        """
        enhanced_prompt = prompt
        images_processed = 0

        # Initialize image cache
        self._current_images_base64 = []

        # Enhanced regex pattern for matching image paths
        # Matches only the path ending with image file extensions
        image_path_pattern = (
            r"Image Path:\s*([^\r\n]*?\.(?:jpg|jpeg|png|gif|bmp|webp|tiff|tif))"
        )

        # First, let's see what matches we find
        matches = re.findall(image_path_pattern, prompt)
        self.logger.info(f"Found {len(matches)} image path matches in prompt")

        def replace_image_path(match):
            nonlocal images_processed

            image_path = match.group(1).strip()
            self.logger.debug(f"Processing image path: '{image_path}'")

            # Validate path format (basic check)
            if not image_path or len(image_path) < 3:
                self.logger.warning(f"Invalid image path format: {image_path}")
                return match.group(0)  # Keep original

            # Use utility function to validate image file
            self.logger.debug(f"Calling validate_image_file for: {image_path}")
            is_valid = validate_image_file(image_path)
            self.logger.debug(f"Validation result for {image_path}: {is_valid}")

            if not is_valid:
                self.logger.warning(f"Image validation failed for: {image_path}")
                return match.group(0)  # Keep original if validation fails

            try:
                # Encode image to base64 using utility function
                self.logger.debug(f"Attempting to encode image: {image_path}")
                image_base64 = encode_image_to_base64(image_path)
                if image_base64:
                    images_processed += 1
                    # Save base64 to instance variable for later use
                    self._current_images_base64.append(image_base64)

                    # Keep original path info and add VLM marker
                    result = f"Image Path: {image_path}\n[VLM_IMAGE_{images_processed}]"
                    self.logger.debug(
                        f"Successfully processed image {images_processed}: {image_path}"
                    )
                    return result
                else:
                    self.logger.error(f"Failed to encode image: {image_path}")
                    return match.group(0)  # Keep original if encoding failed

            except Exception as e:
                self.logger.error(f"Failed to process image {image_path}: {e}")
                return match.group(0)  # Keep original

        # Execute replacement
        enhanced_prompt = re.sub(
            image_path_pattern, replace_image_path, enhanced_prompt
        )

        return enhanced_prompt, images_processed

    def _build_vlm_messages_with_images(
        self, enhanced_prompt: str, user_query: str, system_prompt: str
    ) -> List[Dict]:
        """
        Build VLM message format, using markers to correspond images with text positions

        Args:
            enhanced_prompt: Enhanced prompt with image markers
            user_query: User query

        Returns:
            List[Dict]: VLM message format
        """
        images_base64 = getattr(self, "_current_images_base64", [])

        if not images_base64:
            # Pure text mode
            return [
                {
                    "role": "user",
                    "content": f"Context:\n{enhanced_prompt}\n\nUser Question: {user_query}",
                }
            ]

        # Build multimodal content
        content_parts = []

        # Split text at image markers and insert images
        text_parts = enhanced_prompt.split("[VLM_IMAGE_")

        for i, text_part in enumerate(text_parts):
            if i == 0:
                # First text part
                if text_part.strip():
                    content_parts.append({"type": "text", "text": text_part})
            else:
                # Find marker number and insert corresponding image
                marker_match = re.match(r"(\d+)\](.*)", text_part, re.DOTALL)
                if marker_match:
                    image_num = (
                        int(marker_match.group(1)) - 1
                    )  # Convert to 0-based index
                    remaining_text = marker_match.group(2)

                    # Insert corresponding image
                    if 0 <= image_num < len(images_base64):
                        content_parts.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{images_base64[image_num]}"
                                },
                            }
                        )

                    # Insert remaining text
                    if remaining_text.strip():
                        content_parts.append({"type": "text", "text": remaining_text})

        # Add user question
        content_parts.append(
            {
                "type": "text",
                "text": f"\n\nUser Question: {user_query}\n\nPlease answer based on the context and images provided.",
            }
        )
        base_system_prompt = "You are a helpful assistant that can analyze both text and image content to provide comprehensive answers."

        if system_prompt:
            full_system_prompt = base_system_prompt + " " + system_prompt
        else:
            full_system_prompt = base_system_prompt

        return [
            {
                "role": "system",
                "content": full_system_prompt,
            },
            {
                "role": "user",
                "content": content_parts,
            },
        ]

    async def _call_vlm_with_multimodal_content(self, messages: List[Dict]) -> str:
        """
        Call VLM to process multimodal content

        Args:
            messages: VLM message format

        Returns:
            str: VLM response result
        """
        try:
            user_message = messages[1]
            content = user_message["content"]
            system_prompt = messages[0]["content"]

            if isinstance(content, str):
                # Pure text mode
                result = await self.vision_model_func(
                    content, system_prompt=system_prompt
                )
            else:
                # Multimodal mode - pass complete messages directly to VLM
                result = await self.vision_model_func(
                    "",  # Empty prompt since we're using messages format
                    messages=messages,
                )

            return result

        except Exception as e:
            self.logger.error(f"VLM call failed: {e}")
            raise

    # Synchronous versions of query methods
    def query(self, query: str, mode: str = "mix", **kwargs) -> str:
        """
        Synchronous version of pure text query

        Args:
            query: Query text
            mode: Query mode ("local", "global", "hybrid", "naive", "mix", "bypass")
            **kwargs: Other query parameters, will be passed to QueryParam
                - vlm_enhanced: bool, default True when vision_model_func is available.
                  If True, will parse image paths in retrieved context and replace them
                  with base64 encoded images for VLM processing.

        Returns:
            str: Query result
        """
        loop = always_get_an_event_loop()
        return loop.run_until_complete(self.aquery(query, mode=mode, **kwargs))

    def query_with_multimodal(
        self,
        query: str,
        multimodal_content: List[Dict[str, Any]] = None,
        mode: str = "mix",
        **kwargs,
    ) -> str:
        """
        Synchronous version of multimodal query

        Args:
            query: Base query text
            multimodal_content: List of multimodal content, each element contains:
                - type: Content type ("image", "table", "equation", etc.)
                - Other fields depend on type (e.g., img_path, table_data, latex, etc.)
            mode: Query mode ("local", "global", "hybrid", "naive", "mix", "bypass")
            **kwargs: Other query parameters, will be passed to QueryParam

        Returns:
            str: Query result
        """
        loop = always_get_an_event_loop()
        return loop.run_until_complete(
            self.aquery_with_multimodal(query, multimodal_content, mode=mode, **kwargs)
        )
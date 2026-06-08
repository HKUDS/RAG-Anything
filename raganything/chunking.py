"""
RAG-Anything 多种文本分块策略

每个策略函数签名遵循 LightRAG chunking_func 规范：
    (tokenizer, content, split_by_character, split_by_character_only,
     chunk_overlap_token_size, chunk_token_size) -> list[dict]

其中 dict 格式: {"tokens": int, "content": str, "chunk_order_index": int}

策略说明:
    - fixed_size:    固定大小切割（默认，零额外成本）
    - recursive:     递归字符分割（段落→句子→字符，零额外成本）
    - sentence:      句子级语义分割（零额外成本）
    - structure:     文档结构感知（按标题/章节，零额外成本）
    - semantic:      语义相似度分块（需调用 Embedding API，成本中等）
    - agentic:       LLM 智能分块（需调用 LLM API，成本较高）
"""
from __future__ import annotations

import re
import math
import logging
from typing import Any, Callable

logger = logging.getLogger("raganything.chunking")

# LightRAG's built-in fixed-size chunking is used as a fallback by
# semantic and agentic strategies.  The symbol lives in a private
# module so we guard the import to stay compatible with older LightRAG
# versions that may not expose it.
try:
    from lightrag.operate import chunking_by_token_size
except ImportError:
    chunking_by_token_size = None

# 可被 markdown 标题识别的正则
HEADING_PATTERN = re.compile(r"^#{1,6}\s+", re.MULTILINE)
# 中英文句子分割
SENTENCE_PATTERN = re.compile(
    r"(?<=[。！？.!?\n])\s*",
    re.MULTILINE,
)


# ═══════════════════════════════════════════════════════════
# 1. 递归字符分割 (Recursive Character Splitting)
# ═══════════════════════════════════════════════════════════
# 策略: 段落 → 换行 → 句号 → 分号 → 逗号 → 空格 → 字符
# 费用: 🟢 零额外成本（纯本地算法）

def recursive_chunking(
    tokenizer,
    content: str,
    split_by_character: str | None = None,
    split_by_character_only: bool = False,
    chunk_overlap_token_size: int = 100,
    chunk_token_size: int = 800,
) -> list[dict[str, Any]]:
    """递归字符分割：按优先级依次尝试分隔符，尽量在自然边界切割"""

    separators = ["\n\n", "\n", "。", "？", "！", ". ", "? ", "! ",
                  "；", ";", "，", ", ", " ", ""]

    if split_by_character:
        separators.insert(0, split_by_character)

    def _split_recursive(text: str, seps: list[str]) -> list[str]:
        if not text.strip():
            return []
        sep = seps[0]
        if sep == "":
            # Last resort: force-split by character to avoid single oversized chunk
            if len(text) <= 100:
                return [text]
            # Split into segments of ~500 chars to enable further processing
            result = []
            for i in range(0, len(text), 500):
                result.append(text[i:i+500])
            return result

        if sep in text:
            parts = text.split(sep)
            result = []
            for part in parts:
                stripped = part.strip()
                if stripped:
                    result.append(stripped + (sep if sep not in ("", " ") else ""))
                elif sep == "\n\n":
                    pass  # Empty paragraph, skip
                else:
                    result.append(part)
            return result if result else [text]
        else:
            return _split_recursive(text, seps[1:])

    def _merge_to_size(segments: list[str], max_tokens: int) -> list[tuple[str, int]]:
        """Merge segments into token-limited chunks.

        Returns a list of (chunk_text, token_count) tuples so the caller
        can reuse the already-computed token counts.
        """
        chunks: list[tuple[str, int]] = []
        current = ""
        current_tokens = 0
        for seg in segments:
            seg_tokens = len(tokenizer.encode(seg))
            if current_tokens + seg_tokens <= max_tokens:
                current += seg
                current_tokens += seg_tokens
            else:
                if current.strip():
                    chunks.append((current, current_tokens))
                # If single segment exceeds limit, force-split by token
                if seg_tokens > max_tokens:
                    tokens = tokenizer.encode(seg)
                    step = max(1, max_tokens - chunk_overlap_token_size)
                    for start in range(0, len(tokens), step):
                        chunk_content = tokenizer.decode(tokens[start:start + max_tokens])
                        if chunk_content.strip():
                            chunk_tokens = min(max_tokens, len(tokens) - start)
                            chunks.append((chunk_content.strip(), chunk_tokens))
                    current = ""
                    current_tokens = 0
                else:
                    current = seg
                    current_tokens = seg_tokens
        if current.strip():
            chunks.append((current, current_tokens))
        return chunks

    # Phase 1: Split recursively
    segments = _split_recursive(content, separators.copy())

    # Phase 2: Merge segments to target size (returns pre-computed token counts)
    merged = _merge_to_size(segments, chunk_token_size)

    # Build results — reuse token counts from merge step
    results = []
    for i, (chunk_text, chunk_token_count) in enumerate(merged):
        results.append({
            "tokens": chunk_token_count,
            "content": chunk_text.strip(),
            "chunk_order_index": i,
        })
    return results


# ═══════════════════════════════════════════════════════════
# 2. 句子级语义分割 (Sentence-Level Splitting)
# ═══════════════════════════════════════════════════════════
# 策略: 精确识别句子边界，只在句末切割
# 费用: 🟢 零额外成本（基于正则，纯本地算法）

def sentence_chunking(
    tokenizer,
    content: str,
    split_by_character: str | None = None,
    split_by_character_only: bool = False,
    chunk_overlap_token_size: int = 100,
    chunk_token_size: int = 800,
) -> list[dict[str, Any]]:
    """句子级分割：先精确拆句，再合并到目标大小，保证不在句中切断"""

    # Phase 1: Split into sentences
    raw_sentences = SENTENCE_PATTERN.split(content)
    sentences = [s.strip() for s in raw_sentences if s.strip()]

    if not sentences:
        sentences = [content]

    # Phase 2: Merge sentences into chunks of target token size
    results = []
    current_chunk = ""
    current_tokens = 0
    chunk_index = 0

    for sent in sentences:
        sent_tokens = len(tokenizer.encode(sent))

        # If single sentence exceeds token limit, split it by token size
        if sent_tokens > chunk_token_size:
            # Save current chunk first
            if current_chunk.strip():
                results.append({
                    "tokens": current_tokens,
                    "content": current_chunk.strip(),
                    "chunk_order_index": chunk_index,
                })
                chunk_index += 1
                current_chunk = ""
                current_tokens = 0

            # Force-split long sentence
            tokens = tokenizer.encode(sent)
            for start in range(0, len(tokens), chunk_token_size - chunk_overlap_token_size):
                chunk_content = tokenizer.decode(tokens[start:start + chunk_token_size])
                results.append({
                    "tokens": min(chunk_token_size, len(tokens) - start),
                    "content": chunk_content.strip(),
                    "chunk_order_index": chunk_index,
                })
                chunk_index += 1
            continue

        if current_tokens + sent_tokens <= chunk_token_size:
            current_chunk += sent + " "
            current_tokens += sent_tokens + 1
        else:
            if current_chunk.strip():
                results.append({
                    "tokens": current_tokens,
                    "content": current_chunk.strip(),
                    "chunk_order_index": chunk_index,
                })
                chunk_index += 1
            current_chunk = sent + " "
            current_tokens = sent_tokens + 1

    # Don't forget the last chunk
    if current_chunk.strip():
        results.append({
            "tokens": current_tokens,
            "content": current_chunk.strip(),
            "chunk_order_index": chunk_index,
        })

    return results


# ═══════════════════════════════════════════════════════════
# 3. 文档结构感知 (Structure-Aware Chunking)
# ═══════════════════════════════════════════════════════════
# 策略: 识别 Markdown 标题、HTML 标签、PDF 页标记等结构符号
# 费用: 🟢 零额外成本（纯本地算法）

def structure_chunking(
    tokenizer,
    content: str,
    split_by_character: str | None = None,
    split_by_character_only: bool = False,
    chunk_overlap_token_size: int = 100,
    chunk_token_size: int = 800,
) -> list[dict[str, Any]]:
    """文档结构感知：优先在标题/章节边界切割，保留文档逻辑结构"""

    # Phase 1: Split at heading boundaries
    # Find all heading positions
    heading_positions = []
    for match in HEADING_PATTERN.finditer(content):
        heading_positions.append((match.start(), match.group()))

    # Split content into sections at heading boundaries
    sections = []
    if heading_positions:
        # Section before first heading
        if heading_positions[0][0] > 0:
            pre = content[:heading_positions[0][0]].strip()
            if pre:
                sections.append(("", pre))

        # Sections at each heading
        for i, (pos, heading) in enumerate(heading_positions):
            next_pos = heading_positions[i + 1][0] if i + 1 < len(heading_positions) else len(content)
            section_text = content[pos:next_pos]
            sections.append((heading.strip(), section_text.strip()))
    else:
        sections.append(("", content))

    # Phase 2: For each section, if it exceeds token limit, split by paragraphs
    results = []
    chunk_index = 0
    current_chunk = ""
    current_tokens = 0

    for heading, section_text in sections:
        # Try to keep sections together if they fit
        section_tokens = len(tokenizer.encode(section_text))
        heading_prefix = heading + "\n" if heading else ""

        if section_tokens <= chunk_token_size:
            # Section fits in one chunk
            section_with_heading = heading_prefix + section_text
            section_with_heading_tokens = len(tokenizer.encode(section_with_heading))

            if current_tokens + section_with_heading_tokens <= chunk_token_size:
                current_chunk += ("\n\n" if current_chunk else "") + section_with_heading
                current_tokens += section_with_heading_tokens
            else:
                # Flush current chunk
                if current_chunk.strip():
                    results.append({
                        "tokens": current_tokens,
                        "content": current_chunk.strip(),
                        "chunk_order_index": chunk_index,
                    })
                    chunk_index += 1
                current_chunk = section_with_heading
                current_tokens = section_with_heading_tokens
        else:
            # Section too large, flush current and split section by paragraphs
            if current_chunk.strip():
                results.append({
                    "tokens": current_tokens,
                    "content": current_chunk.strip(),
                    "chunk_order_index": chunk_index,
                })
                chunk_index += 1
                current_chunk = ""
                current_tokens = 0

            # Split section by paragraphs
            paragraphs = section_text.split("\n\n")
            for para in paragraphs:
                para_text = heading_prefix + para.strip() if not current_chunk else para.strip()
                para_tokens = len(tokenizer.encode(para_text))

                if para_tokens > chunk_token_size:
                    # Flush current first
                    if current_chunk.strip():
                        results.append({
                            "tokens": current_tokens,
                            "content": current_chunk.strip(),
                            "chunk_order_index": chunk_index,
                        })
                        chunk_index += 1
                        current_chunk = ""
                        current_tokens = 0

                    # Force-split long paragraph
                    tokens = tokenizer.encode(para_text)
                    for start in range(0, len(tokens), chunk_token_size - chunk_overlap_token_size):
                        results.append({
                            "tokens": min(chunk_token_size, len(tokens) - start),
                            "content": tokenizer.decode(tokens[start:start + chunk_token_size]).strip(),
                            "chunk_order_index": chunk_index,
                        })
                        chunk_index += 1
                elif current_tokens + para_tokens <= chunk_token_size:
                    current_chunk += ("\n\n" if current_chunk else "") + para_text
                    current_tokens += para_tokens
                else:
                    results.append({
                        "tokens": current_tokens,
                        "content": current_chunk.strip(),
                        "chunk_order_index": chunk_index,
                    })
                    chunk_index += 1
                    current_chunk = para_text
                    current_tokens = para_tokens

    # Last chunk
    if current_chunk.strip():
        results.append({
            "tokens": current_tokens,
            "content": current_chunk.strip(),
            "chunk_order_index": chunk_index,
        })

    if not results:
        # Fallback: at least return the whole content
        tokens = tokenizer.encode(content)
        results.append({
            "tokens": len(tokens),
            "content": content.strip(),
            "chunk_order_index": 0,
        })

    return results


# ═══════════════════════════════════════════════════════════
# 4. 语义相似度分块 (Semantic Chunking)
# ═══════════════════════════════════════════════════════════
# 策略: 将文本拆为段落，计算相邻段落 embedding 相似度
#       相似度骤降之处即为语义边界
# 费用: 🟡 中等成本（约 N*2 次 Embedding API 调用，N = 段落数）

def make_semantic_chunking(embedding_func):
    """创建语义分块函数（工厂模式，注入 embedding 函数）

    Args:
        embedding_func: LightRAG 风格的 embedding 函数，
                       调用方式: embedding_func([text1, text2, ...])
                       返回: list[list[float]] (embedding vectors)

    Returns:
        chunking_func: 符合 LightRAG chunking_func 规范的异步函数
    """

    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """计算两个向量的余弦相似度"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    async def semantic_chunking(
        tokenizer,
        content: str,
        split_by_character: str | None = None,
        split_by_character_only: bool = False,
        chunk_overlap_token_size: int = 100,
        chunk_token_size: int = 800,
    ) -> list[dict[str, Any]]:
        """语义分块：通过 embedding 相似度识别语义边界"""

        # Phase 1: Split into paragraphs
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        if len(paragraphs) <= 1:
            # Single paragraph: fallback to fixed-size
            if chunking_by_token_size is None:
                return recursive_chunking(
                    tokenizer, content, split_by_character,
                    split_by_character_only, chunk_overlap_token_size, chunk_token_size,
                )
            return chunking_by_token_size(
                tokenizer, content, split_by_character,
                split_by_character_only, chunk_overlap_token_size, chunk_token_size,
            )

        # Phase 2: Compute paragraph embeddings
        try:
            embeddings = await embedding_func(paragraphs)
        except Exception as e:
            logger.warning(f"Semantic chunking embedding failed: {e}, falling back to recursive")
            return recursive_chunking(
                tokenizer, content, split_by_character,
                split_by_character_only, chunk_overlap_token_size, chunk_token_size,
            )

        # Phase 3: Compute similarity between adjacent paragraphs
        similarities = []
        for i in range(len(paragraphs) - 1):
            sim = _cosine_similarity(embeddings[i], embeddings[i + 1])
            similarities.append(sim)

        if not similarities:
            if chunking_by_token_size is None:
                return recursive_chunking(
                    tokenizer, content, split_by_character,
                    split_by_character_only, chunk_overlap_token_size, chunk_token_size,
                )
            return chunking_by_token_size(
                tokenizer, content, split_by_character,
                split_by_character_only, chunk_overlap_token_size, chunk_token_size,
            )

        # Phase 4: Find semantic boundaries (similarity drops)
        # Adaptive threshold: median - 0.5 * std
        mean_sim = sum(similarities) / len(similarities)
        variance = sum((s - mean_sim) ** 2 for s in similarities) / len(similarities)
        std_sim = math.sqrt(variance)
        threshold = max(0.3, mean_sim - 0.8 * std_sim)  # Lower bound of 0.3

        # Find split points where similarity drops below threshold
        split_indices = []
        for i, sim in enumerate(similarities):
            if sim < threshold:
                split_indices.append(i + 1)  # Split after paragraph i

        # Phase 5: Merge paragraphs between split points into chunks
        chunks = []
        start = 0
        for split_idx in split_indices + [len(paragraphs)]:
            if split_idx > start:
                segment = "\n\n".join(paragraphs[start:split_idx])
                seg_tokens = len(tokenizer.encode(segment))
                if seg_tokens <= chunk_token_size * 2:
                    chunks.append(segment)
                else:
                    # Sub-split oversized segment
                    sub_tokens = tokenizer.encode(segment)
                    for s in range(0, len(sub_tokens), chunk_token_size - chunk_overlap_token_size):
                        chunks.append(tokenizer.decode(sub_tokens[s:s + chunk_token_size]))
                start = split_idx

        if not chunks:
            chunks = ["\n\n".join(paragraphs)]

        # Build results
        results = []
        for i, chunk_text in enumerate(chunks):
            chunk_tokens = tokenizer.encode(chunk_text)
            results.append({
                "tokens": len(chunk_tokens),
                "content": chunk_text.strip(),
                "chunk_order_index": i,
            })
        return results

    return semantic_chunking


# ═══════════════════════════════════════════════════════════
# 5. LLM 智能分块 (Agentic Chunking)
# ═══════════════════════════════════════════════════════════
# 策略: 让 LLM 分析文本结构，标注语义断点，再按标注切割
# 费用: 🔴 较高成本（每次分块需 1 次 LLM API 调用）

AGENTIC_CHUNK_PROMPT = """你是一个专业的文本结构分析专家。请分析以下文本，找出最佳的语义分割点。

## 任务
阅读文本，在**话题转换、章节切换、语义跳跃**的位置标注分割点。

## 输出格式
只输出分割点的索引（从0开始的行号），每行一个数字，不要输出其他内容。
例如：
3
7
12

这表示在第3行后、第7行后、第12行后分割。

## 注意
- 在自然的话题转换处分割，不要在不该切的地方切
- 分割不要太过频繁，每个分块应包含足够的内容
- 总分割点不要超过20个
- 如果文本较短或结构清晰，可以输出较少的分割点

## 文本内容
"""


def make_agentic_chunking(llm_func, model_name: str = "qwen-plus"):
    """创建 LLM 智能分块函数（工厂模式，注入 LLM 函数）

    Args:
        llm_func: LLM 调用函数，签名: (prompt, system_prompt, history_messages, **kw) -> str
        model_name: 使用的模型名称

    Returns:
        chunking_func: 符合 LightRAG chunking_func 规范的异步函数
    """

    async def agentic_chunking(
        tokenizer,
        content: str,
        split_by_character: str | None = None,
        split_by_character_only: bool = False,
        chunk_overlap_token_size: int = 100,
        chunk_token_size: int = 800,
    ) -> list[dict[str, Any]]:
        """LLM 智能分块：让 LLM 分析语义断点后切割"""

        # Phase 1: Prepare text for LLM analysis (add line numbers)
        lines = content.split("\n")
        # Limit: only analyze first 500 lines to avoid excessive tokens
        total_lines = len(lines)
        if total_lines > 500:
            logger.warning(
                f"Agentic chunking: analyzing only first 500 of {total_lines} lines "
                f"({total_lines - 500} lines after line 500 will be appended to the final segment)"
            )
            numbered_text = "\n".join(f"{i}: {line}" for i, line in enumerate(lines[:500]))
        else:
            numbered_text = "\n".join(f"{i}: {line}" for i, line in enumerate(lines))

        prompt = AGENTIC_CHUNK_PROMPT + numbered_text

        # Phase 2: Call LLM to identify split points
        try:
            response = await llm_func(
                prompt,
                system_prompt="你是一个文本结构分析专家，精确标注语义分割点。",
                history_messages=[],
                temperature=0.1,
                max_tokens=500,
            )
        except Exception as e:
            logger.warning(f"Agentic chunking LLM call failed: {e}, falling back to recursive")
            return recursive_chunking(
                tokenizer, content, split_by_character,
                split_by_character_only, chunk_overlap_token_size, chunk_token_size,
            )

        # Phase 3: Parse LLM response to get split indices
        split_indices = set()
        for line_text in response.strip().split("\n"):
            line_text = line_text.strip().rstrip(".")
            try:
                idx = int(line_text)
                if 0 <= idx < len(lines):
                    split_indices.add(idx)
            except ValueError:
                continue

        if not split_indices:
            # LLM didn't find any split points, fallback
            return recursive_chunking(
                tokenizer, content, split_by_character,
                split_by_character_only, chunk_overlap_token_size, chunk_token_size,
            )

        # Phase 4: Split text at LLM-identified boundaries
        sorted_indices = sorted(split_indices)
        segments = []
        start = 0
        for idx in sorted_indices:
            segments.append("\n".join(lines[start:idx + 1]))
            start = idx + 1
        if start < len(lines):
            segments.append("\n".join(lines[start:]))

        # Phase 5: Merge segments into target-sized chunks
        results = []
        current_chunk = ""
        current_tokens = 0
        chunk_index = 0

        for seg in segments:
            seg_tokens = len(tokenizer.encode(seg))
            if seg_tokens > chunk_token_size:
                # Flush current chunk
                if current_chunk.strip():
                    results.append({
                        "tokens": current_tokens,
                        "content": current_chunk.strip(),
                        "chunk_order_index": chunk_index,
                    })
                    chunk_index += 1
                    current_chunk = ""
                    current_tokens = 0
                # Force-split oversized segment
                tokens = tokenizer.encode(seg)
                for s in range(0, len(tokens), chunk_token_size - chunk_overlap_token_size):
                    results.append({
                        "tokens": min(chunk_token_size, len(tokens) - s),
                        "content": tokenizer.decode(tokens[s:s + chunk_token_size]).strip(),
                        "chunk_order_index": chunk_index,
                    })
                    chunk_index += 1
            elif current_tokens + seg_tokens <= chunk_token_size:
                current_chunk += ("\n\n" if current_chunk else "") + seg
                current_tokens += seg_tokens
            else:
                results.append({
                    "tokens": current_tokens,
                    "content": current_chunk.strip(),
                    "chunk_order_index": chunk_index,
                })
                chunk_index += 1
                current_chunk = seg
                current_tokens = seg_tokens

        if current_chunk.strip():
            results.append({
                "tokens": current_tokens,
                "content": current_chunk.strip(),
                "chunk_order_index": chunk_index,
            })

        if not results:
            tokens = tokenizer.encode(content)
            results.append({
                "tokens": len(tokens),
                "content": content.strip(),
                "chunk_order_index": 0,
            })

        return results

    return agentic_chunking


# ═══════════════════════════════════════════════════════════
# 策略注册表
# ═══════════════════════════════════════════════════════════

STRATEGY_META = {
    "fixed_size": {
        "name": "固定大小切割",
        "description": "按 Token 数固定切割，使用重叠窗口",
        "cost": "🟢 零额外成本",
        "cost_level": "free",
    },
    "recursive": {
        "name": "递归字符分割",
        "description": "段落→句子→字符，逐级尝试自然边界",
        "cost": "🟢 零额外成本（推荐）",
        "cost_level": "free",
    },
    "sentence": {
        "name": "句子级语义分割",
        "description": "精确识别句边界，保证句子完整性",
        "cost": "🟢 零额外成本",
        "cost_level": "free",
    },
    "structure": {
        "name": "文档结构感知",
        "description": "按标题/章节结构切分，保留文档逻辑",
        "cost": "🟢 零额外成本",
        "cost_level": "free",
    },
    "semantic": {
        "name": "语义相似度分块",
        "description": "基于 Embedding 相似度，在语义边界处切割",
        "cost": "🟡 中等成本（每段落约 2 次 Embedding 调用）",
        "cost_level": "medium",
    },
    "agentic": {
        "name": "LLM 智能分块",
        "description": "LLM 自主判断最佳分割点，效果最优",
        "cost": "🔴 较高成本（每次分块需 1 次 LLM 调用 + 约 500 Token）",
        "cost_level": "high",
    },
}


# ═══════════════════════════════════════════════════════════
# 辅助：从 LightRAG 实例构建分块函数
# ═══════════════════════════════════════════════════════════

def build_chunking_func(strategy: str, lightrag_instance):
    """根据策略名称和已有的 LightRAG 实例构建分块函数

    用于上传时动态切换分块策略，无需重建整个 RAG 实例。

    Args:
        strategy: 策略名称（recursive/sentence/structure/semantic/agentic/fixed_size）
        lightrag_instance: LightRAG 实例（用于获取 embedding_func 和 llm_model_func）

    Returns:
        chunking_func 或 None（使用默认）
    """
    if strategy in ("fixed_size", "", None):
        return None

    if strategy == "recursive":
        return recursive_chunking

    if strategy == "sentence":
        return sentence_chunking

    if strategy == "structure":
        return structure_chunking

    # 语义分块需要 embedding_func
    if strategy == "semantic":
        embed_func = getattr(lightrag_instance, "embedding_func", None)
        if embed_func is None:
            logger.warning("semantic chunking requires embedding_func, falling back to recursive")
            return recursive_chunking

        # LightRAG 的 embedding_func 是 EmbeddingFunc 对象，func 属性是实际函数
        actual_embed = getattr(embed_func, "func", embed_func)

        async def _embed_wrapper(texts: list[str]) -> list[list[float]]:
            return await actual_embed(texts)

        return make_semantic_chunking(_embed_wrapper)

    # 智能分块需要 llm_model_func
    if strategy == "agentic":
        llm_func = getattr(lightrag_instance, "llm_model_func", None)
        if llm_func is None:
            logger.warning("agentic chunking requires llm_model_func, falling back to recursive")
            return recursive_chunking

        async def _llm_wrapper(prompt: str, system_prompt: str = "",
                               history_messages=None, **kw):
            return await llm_func(prompt, system_prompt=system_prompt,
                                  history_messages=history_messages or [], **kw)

        model = getattr(lightrag_instance, "llm_model_name", "qwen-plus")
        return make_agentic_chunking(_llm_wrapper, model)

    logger.warning(f"Unknown chunking strategy: {strategy}, using default")
    return None

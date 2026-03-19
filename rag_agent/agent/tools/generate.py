"""Generate tool for grounded answer synthesis in rag_agent."""

from __future__ import annotations

import json
from typing import Any

from rag_agent.llm.base import LLMProvider

from .base import Tool


class GenerateTool(Tool):
    """Generate final answer from question and retrieval evidence."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        rag: Any | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1200,
        multimodal_mode: str = "mix",
        max_context_chars: int = 120000,
    ) -> None:
        self.provider = provider
        self.rag = rag
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.multimodal_mode = multimodal_mode
        self.max_context_chars = max_context_chars

    @property
    def name(self) -> str:
        return "generate"

    @property
    def description(self) -> str:
        return (
            "Generate grounded final answer using user question and retrieve output object. "
            "Supports multimodal enhancement when evidence contains image paths. "
            "Returns a JSON string with keys: status, answer, used_multimodal, citations, evidence_stats, message."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Original user question."},
                "retrieval_result": {
                    "type": "object",
                    "description": "Parsed JSON object returned by retrieve tool (do not wrap as string).",
                },
                "style": {
                    "type": "string",
                    "enum": ["concise", "balanced", "detailed"],
                    "description": "Answer style preference.",
                },
                "language": {
                    "type": "string",
                    "description": "Output language, e.g. zh-CN or en-US.",
                },
                "include_citations": {
                    "type": "boolean",
                    "description": "Whether to include source citations in output.",
                },
            },
            "required": ["question", "retrieval_result"],
        }

    async def execute(self, **kwargs: Any) -> str:
        question = str(kwargs.get("question", "")).strip()
        retrieval_result = kwargs.get("retrieval_result")
        style = str(kwargs.get("style", "balanced") or "balanced")
        language = str(kwargs.get("language", "zh-CN") or "zh-CN")
        include_citations = bool(kwargs.get("include_citations", True))

        if not question:
            return self._json(
                {
                    "status": "failure",
                    "answer": "",
                    "used_multimodal": False,
                    "citations": [],
                    "evidence_stats": {},
                    "message": "generate tool error: empty question",
                }
            )
        json_file = "retrieval_result.json"
        with open(json_file, "w", encoding="utf-8") as file:
            json.dump(retrieval_result, file, ensure_ascii=False, indent=2)
        parsed = self._parse_retrieval_result(retrieval_result)
        if not isinstance(parsed, dict):
            return self._json(
                {
                    "status": "failure",
                    "answer": "",
                    "used_multimodal": False,
                    "citations": [],
                    "evidence_stats": {},
                    "message": "generate tool error: retrieval_result must be a JSON object",
                }
            )

        evidence, stats = self._extract_evidence(parsed)

        json_file = "evidence.json"
        with open(json_file, "w", encoding="utf-8") as file:
            json.dump(evidence, file, ensure_ascii=False, indent=2)
        has_evidence = any(stats.get(k, 0) > 0 for k in ("chunks", "entities", "relationships"))
        if parsed.get("status") != "success" or not has_evidence:
            return self._json(
                {
                    "status": "failure",
                    "answer": "我目前没有足够的检索证据来可靠回答这个问题。",
                    "used_multimodal": False,
                    "citations": [],
                    "evidence_stats": stats,
                    "message": str(parsed.get("message") or "weak or empty retrieval evidence"),
                }
            )

        context_text = self._build_lightrag_context(evidence)

        used_multimodal = False
        answer = ""

        # Preferred path: reuse RAGAnything VLM pipeline from retrieval-derived context.
        if self.rag is not None:
            vlm_answer = await self._run_rag_vlm_pipeline(
                rag=self.rag,
                context_text=context_text,
                question=question,
                style=style,
                language=language,
                include_citations=include_citations,
            )
            if vlm_answer is not None:
                answer = vlm_answer
                used_multimodal = True

        if not answer and self.provider is not None:
            messages = self._build_llm_messages(
                question=question,
                text_context=context_text,
                style=style,
                language=language,
                include_citations=include_citations,
            )
            response = await self.provider.chat_with_retry(
                messages=messages,
                tools=None,
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            answer = (response.content or "").strip()

        if not answer:
            answer = self._fallback_answer(question=question, text_context=context_text)

        citations = self._build_citations(evidence) if include_citations else []

        return self._json(
            {
                "status": "success",
                "answer": answer,
                "used_multimodal": used_multimodal,
                "citations": citations,
                "evidence_stats": stats,
                "message": "ok",
            }
        )

    @staticmethod
    def _json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _parse_retrieval_result(raw: Any) -> dict[str, Any] | None:
        if isinstance(raw, dict):
            # Backward-compat: when provider falls back to {"_raw": "..."}, try one more decode.
            only_raw_key = set(raw.keys()) == {"_raw"}
            if only_raw_key:
                nested = raw.get("_raw")
                if isinstance(nested, str) and nested.strip():
                    try:
                        reparsed = json.loads(nested)
                    except json.JSONDecodeError:
                        return None
                    return reparsed if isinstance(reparsed, dict) else None
            return raw

        if not isinstance(raw, str):
            return None

        text = raw.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _as_list(data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, list):
            return []
        return [x for x in data if isinstance(x, dict)]

    def _extract_evidence(self, parsed: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
        evidence = parsed.get("evidence") if isinstance(parsed.get("evidence"), dict) else {}
        entities = self._as_list(evidence.get("entities"))
        relationships = self._as_list(evidence.get("relationships"))
        chunks = self._as_list(evidence.get("chunks"))
        references = self._as_list(evidence.get("references"))

        counts = parsed.get("counts") if isinstance(parsed.get("counts"), dict) else {}
        stats = {
            "entities": int(counts.get("entities", len(entities))),
            "relationships": int(counts.get("relationships", len(relationships))),
            "chunks": int(counts.get("chunks", len(chunks))),
            "references": int(counts.get("references", len(references))),
        }

        return (
            {
                "entities": entities,
                "relationships": relationships,
                "chunks": chunks,
                "references": references,
            },
            stats,
        )

    def _build_text_context(self, evidence: dict[str, list[dict[str, Any]]]) -> str:
        lines: list[str] = []

        for item in evidence["chunks"][:10]:
            content = str(item.get("content", "")).strip()
            if content:
                lines.append(f"[Chunk] {content}")

        for item in evidence["entities"][:10]:
            name = str(item.get("entity_name", "")).strip()
            desc = str(item.get("description", "")).strip()
            if name or desc:
                lines.append(f"[Entity] {name}: {desc}")

        for item in evidence["relationships"][:10]:
            src = str(item.get("src_id", "")).strip()
            tgt = str(item.get("tgt_id", "")).strip()
            desc = str(item.get("description", "")).strip()
            if src or tgt or desc:
                lines.append(f"[Relation] {src} -> {tgt}: {desc}")

        merged = "\n".join(lines)
        return merged[: self.max_context_chars]

    def _build_lightrag_context(self, evidence: dict[str, list[dict[str, Any]]]) -> str:
        """Build kg_query_context-like string from evidence (final_data-derived)."""
        try:
            from lightrag.prompt import PROMPTS as LG_PROMPTS  # type: ignore
            from lightrag.utils import generate_reference_list_from_chunks  # type: ignore

            entities_context: list[dict[str, Any]] = []
            for item in evidence["entities"]:
                entities_context.append(
                    {
                        "entity": str(item.get("entity_name", "") or "UNKNOWN"),
                        "type": str(item.get("entity_type", "") or "UNKNOWN"),
                        "description": str(item.get("description", "") or "UNKNOWN"),
                    }
                )

            relations_context: list[dict[str, Any]] = []
            for item in evidence["relationships"]:
                relations_context.append(
                    {
                        "entity1": str(item.get("src_id", "") or "UNKNOWN"),
                        "entity2": str(item.get("tgt_id", "") or "UNKNOWN"),
                        "description": str(item.get("description", "") or "UNKNOWN"),
                    }
                )

            chunks: list[dict[str, Any]] = []
            for item in evidence["chunks"]:
                content = str(item.get("content", "")).strip()
                if not content:
                    continue
                chunks.append(
                    {
                        "content": content,
                        "file_path": str(item.get("file_path", "") or "unknown_source"),
                        "chunk_id": str(item.get("chunk_id", "") or ""),
                        "reference_id": self._normalize_reference_id(
                            str(item.get("reference_id", "") or "")
                        ),
                    }
                )

            references_input: list[dict[str, str]] = []
            for ref in evidence["references"]:
                rid = self._normalize_reference_id(str(ref.get("reference_id", "") or ""))
                file_path = str(ref.get("file_path", "") or "").strip()
                if rid and file_path:
                    references_input.append({"reference_id": rid, "file_path": file_path})

            # Reconstruct chunk-reference mapping similar to _build_context_str result.
            if references_input:
                # Deduplicate references while preserving order.
                seen_ref: set[tuple[str, str]] = set()
                reference_list: list[dict[str, str]] = []
                for ref in references_input:
                    key = (ref["reference_id"], ref["file_path"])
                    if key in seen_ref:
                        continue
                    seen_ref.add(key)
                    reference_list.append(ref)

                # Build file_path -> reference_id mapping and backfill chunks without IDs.
                file_to_ref: dict[str, str] = {}
                for ref in reference_list:
                    file_to_ref.setdefault(ref["file_path"], ref["reference_id"])

                chunks_with_ref: list[dict[str, Any]] = []
                for chunk in chunks:
                    ref_id = self._normalize_reference_id(str(chunk.get("reference_id", "") or ""))
                    if not ref_id:
                        ref_id = file_to_ref.get(str(chunk.get("file_path", "") or "").strip(), "")
                    chunk_copy = dict(chunk)
                    chunk_copy["reference_id"] = ref_id
                    chunks_with_ref.append(chunk_copy)
            else:
                # Fallback to LightRAG's helper if references are missing.
                reference_list, chunks_with_ref = generate_reference_list_from_chunks(chunks)

            entities_str = "\n".join(
                json.dumps(entity, ensure_ascii=False) for entity in entities_context
            )
            relations_str = "\n".join(
                json.dumps(relation, ensure_ascii=False) for relation in relations_context
            )
            text_chunks_str = "\n".join(
                json.dumps(
                    {
                        "reference_id": self._normalize_reference_id(
                            str(chunk.get("reference_id", "") or "")
                        ),
                        "content": str(chunk.get("content", "")),
                    },
                    ensure_ascii=False,
                )
                for chunk in chunks_with_ref
            )

            reference_list_str = "\n".join(
                f"[{self._normalize_reference_id(str(ref.get('reference_id', '') or ''))}] {str(ref.get('file_path', '') or '')}"
                for ref in reference_list
                if self._normalize_reference_id(str(ref.get("reference_id", "") or ""))
            )

            template = LG_PROMPTS["kg_query_context"]
            context = template.format(
                entities_str=entities_str,
                relations_str=relations_str,
                text_chunks_str=text_chunks_str,
                reference_list_str=reference_list_str,
            )

            sys_prompt_temp = LG_PROMPTS["rag_response"]
            sys_prompt = sys_prompt_temp.format(
                response_type="Multiple Paragraphs",
                user_prompt="n/a",
                context_data=context,
            )
            len_of_prompts = len(self.rag.lightrag.tokenizer.encode(sys_prompt))
            print(f"context的长度为: {len_of_prompts}")
            return sys_prompt[: self.max_context_chars]
        except Exception:
            return self._build_text_context(evidence)

    @staticmethod
    def _normalize_reference_id(value: str) -> str:
        ref_id = str(value or "").strip()
        if ref_id.startswith("[") and ref_id.endswith("]") and len(ref_id) >= 2:
            ref_id = ref_id[1:-1].strip()
        return ref_id

    async def _run_rag_vlm_pipeline(
        self,
        rag: Any,
        context_text: str,
        question: str,
        style: str,
        language: str,
        include_citations: bool,
    ) -> str | None:
        """Reuse RAGAnything internal VLM path: process image paths -> build messages -> call VLM."""
        required = (
            "_process_image_paths_for_vlm",
            "_build_vlm_messages_with_images",
            "_call_vlm_with_multimodal_content",
            "vision_model_func",
        )
        if not all(hasattr(rag, name) for name in required):
            return None

        try:
            enhanced_prompt, images_found = await rag._process_image_paths_for_vlm(context_text)
            if not images_found:
                return None

            system_prompt = self._build_vlm_system_prompt(
                style=style,
                language=language,
                include_citations=include_citations,
            )
            messages = rag._build_vlm_messages_with_images(
                enhanced_prompt,
                question,
                system_prompt,
            )
            if hasattr(rag, "_save_messages_to_json"):
                rag._save_messages_to_json(messages)
            return await rag._call_vlm_with_multimodal_content(messages)
        except Exception:
            return None

    @staticmethod
    def _build_vlm_system_prompt(style: str, language: str, include_citations: bool) -> str:
        cite_line = "Include citations mapped to reference IDs/file paths." if include_citations else "Citations optional."
        return (
            f"Respond in {language}. "
            f"Style: {style}. "
            "Ground every claim in provided context and images. "
            "If evidence is insufficient, explicitly say uncertainty. "
            f"{cite_line}"
        )

    def _build_llm_messages(
        self,
        question: str,
        text_context: str,
        style: str,
        language: str,
        include_citations: bool,
    ) -> list[dict[str, Any]]:
        system_prompt = (
            "You are a grounded RAG answer generator. "
            "Use only provided evidence. If evidence is insufficient, state uncertainty explicitly."
        )
        cite_line = "Append citations by file path when possible." if include_citations else "No citation list required."
        user_prompt = (
            f"Language: {language}\n"
            f"Style: {style}\n"
            f"{cite_line}\n\n"
            f"Evidence:\n{text_context}\n\n"
            f"Question: {question}"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def _build_citations(evidence: dict[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
        seen: set[tuple[str, str]] = set()
        citations: list[dict[str, str]] = []

        for ref in evidence["references"]:
            reference_id = str(ref.get("reference_id", "")).strip()
            file_path = str(ref.get("file_path", "")).strip()
            key = (reference_id, file_path)
            if file_path and key not in seen:
                seen.add(key)
                citations.append({"reference_id": reference_id, "file_path": file_path})

        for chunk in evidence["chunks"]:
            file_path = str(chunk.get("file_path", "")).strip()
            if not file_path:
                continue
            key = ("", file_path)
            if key not in seen:
                seen.add(key)
                citations.append({"reference_id": "", "file_path": file_path})

        return citations

    @staticmethod
    def _fallback_answer(question: str, text_context: str) -> str:
        if not text_context.strip():
            return "我目前没有足够证据来可靠回答该问题。"
        preview = text_context[:800]
        return (
            "以下是基于检索证据的摘要回答（未调用外部生成模型）：\n"
            f"问题：{question}\n"
            f"证据摘要：\n{preview}"
        )

from __future__ import annotations

import asyncio
import gc
import importlib
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

logger = logging.getLogger("ITERADE")


@dataclass
class ITERADEConfig:
    model_name: str = "fleonce/iter-ade-deberta-large"
    device: str = "cuda"
    split_chunks: bool = True
    max_length: int = 512
    sentence_overlap: int = 1
    empty_cache_each_batch: bool = True
    debug_output: bool = False


class ITERADEExtractor:
    """Adapter that mimics LightRAG extract_entities(...) with ITER + ADE checkpoint."""

    def __init__(self, config: ITERADEConfig):
        self.config = config
        self._model = None
        self._tokenizer = None
        self._debug_logged = False

    def validate(self) -> None:
        self._ensure_model_loaded()

    def _ensure_model_loaded(self):
        if self._model is not None and self._tokenizer is not None:
            return self._model, self._tokenizer

        try:
            iter_module = importlib.import_module("iter")
        except ImportError as exc:
            raise RuntimeError(
                "ITER backend requires the `iter` package. Install it first, e.g. "
                "`/mnt/disk1/aiotlab/envs/raganything/bin/pip install git+https://github.com/fleonce/iter`."
            ) from exc

        try:
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "ITER backend requires `transformers` in the benchmark environment."
            ) from exc

        ITERForRelationExtraction = getattr(iter_module, "ITERForRelationExtraction", None)
        if ITERForRelationExtraction is None:
            raise RuntimeError(
                "Installed `iter` package does not expose ITERForRelationExtraction."
            )

        logger.info(
            "Loading ITER model_name=%s on device=%s",
            self.config.model_name,
            self.config.device,
        )
        model = ITERForRelationExtraction.from_pretrained(self.config.model_name)
        tokenizer = getattr(model, "tokenizer", None)
        if tokenizer is None:
            tokenizer = AutoTokenizer.from_pretrained(self.config.model_name, use_fast=True)

        try:
            model = model.to(self.config.device)
        except Exception:
            logger.warning("Could not move ITER model to device=%s; using default placement", self.config.device)
        model.eval()

        self._model = model
        self._tokenizer = tokenizer
        return self._model, self._tokenizer

    @staticmethod
    def _normalize_text(value: Any) -> str:
        if value is None:
            return ""
        return " ".join(str(value).strip().split()).strip()

    @staticmethod
    def _safe_repr(value: Any, limit: int = 800) -> str:
        try:
            text = repr(value)
        except Exception as exc:
            text = f"<unreprable {type(value).__name__}: {exc}>"
        return text if len(text) <= limit else text[:limit] + "...<truncated>"

    def _debug_log_output(
        self,
        *,
        text: str,
        generation_output: Any,
        entities_raw: list[Any],
        links_raw: list[Any],
        parsed_entity_samples: list[dict[str, Any]],
        parsed_relation_samples: list[dict[str, Any]],
    ) -> None:
        if not self.config.debug_output or self._debug_logged:
            return

        logger.info("ITER DEBUG text sample: %s", self._safe_repr(text[:400]))
        logger.info(
            "ITER DEBUG generation_output types: entities=%s links=%s",
            type(getattr(generation_output, "entities", None)).__name__,
            type(getattr(generation_output, "links", None)).__name__,
        )
        logger.info(
            "ITER DEBUG raw sizes: entities=%d links=%d",
            len(entities_raw),
            len(links_raw),
        )
        if entities_raw:
            logger.info("ITER DEBUG first raw entity: %s", self._safe_repr(entities_raw[0]))
        if links_raw:
            logger.info("ITER DEBUG first raw link: %s", self._safe_repr(links_raw[0]))
        logger.info(
            "ITER DEBUG parsed entity samples: %s",
            self._safe_repr(parsed_entity_samples),
        )
        logger.info(
            "ITER DEBUG parsed relation samples: %s",
            self._safe_repr(parsed_relation_samples),
        )
        self._debug_logged = True

    @classmethod
    def _normalize_entity_name(cls, value: Any) -> str:
        return cls._normalize_text(value)[:255]

    @classmethod
    def _normalize_entity_type(cls, label: Any) -> str:
        text = cls._normalize_text(label).replace(" ", "_").lower()
        return text or "unknown"

    @classmethod
    def _entity_description(cls, entity_name: str, label: Any) -> str:
        label_text = cls._normalize_text(label)
        return f"{entity_name} [{label_text}]" if label_text else entity_name

    @classmethod
    def _relation_keywords(cls, relation_type: Any) -> str:
        text = cls._normalize_text(relation_type).replace(" ", "_").lower()
        return text or "related_to"

    @classmethod
    def _relation_description(cls, source: str, relation_type: Any, target: str) -> str:
        rel = cls._relation_keywords(relation_type)
        return f"{source} {rel} {target}"

    @staticmethod
    def _sentence_units(text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []
        units = [
            unit.strip()
            for unit in re.split(r"(?<=[\.\!\?\:\;])\s+|\n{2,}", text)
            if unit and unit.strip()
        ]
        return units or [text]

    def _token_length(self, text: str) -> int:
        _, tokenizer = self._ensure_model_loaded()
        encoded = tokenizer(
            text,
            add_special_tokens=True,
            truncation=False,
            return_attention_mask=False,
            return_token_type_ids=False,
        )
        input_ids = encoded.get("input_ids", [])
        if isinstance(input_ids, list) and input_ids and isinstance(input_ids[0], list):
            return len(input_ids[0])
        return len(input_ids)

    def _split_long_unit(self, unit: str) -> list[str]:
        words = unit.split()
        if not words:
            return []
        parts: list[str] = []
        current: list[str] = []
        for word in words:
            candidate = " ".join(current + [word]).strip()
            if current and self._token_length(candidate) > self.config.max_length:
                parts.append(" ".join(current).strip())
                overlap = current[-20:] if len(current) > 20 else current[-5:]
                current = list(overlap) + [word]
            else:
                current.append(word)
        if current:
            parts.append(" ".join(current).strip())
        return [part for part in parts if part]

    def _segment_text(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []
        if not self.config.split_chunks:
            return [text]
        if self._token_length(text) <= self.config.max_length:
            return [text]

        units = self._sentence_units(text)
        segments: list[str] = []
        current_units: list[str] = []

        def flush():
            nonlocal current_units
            if current_units:
                segment = " ".join(current_units).strip()
                if segment:
                    segments.append(segment)
            overlap = (
                current_units[-self.config.sentence_overlap :]
                if self.config.sentence_overlap > 0
                else []
            )
            current_units = list(overlap)

        for unit in units:
            if self._token_length(unit) > self.config.max_length:
                if current_units:
                    flush()
                segments.extend(self._split_long_unit(unit))
                current_units = []
                continue

            candidate = " ".join(current_units + [unit]).strip()
            if current_units and self._token_length(candidate) > self.config.max_length:
                flush()
            current_units.append(unit)

        if current_units:
            flush()

        return segments or [text]

    @staticmethod
    def _maybe_attr(obj: Any, *names: str) -> Any:
        if obj is None:
            return None
        if isinstance(obj, dict):
            for name in names:
                if name in obj:
                    return obj[name]
            return None
        for name in names:
            if hasattr(obj, name):
                return getattr(obj, name)
        return None

    def _lookup_label(self, value: Any, *, relation: bool) -> Any:
        if not isinstance(value, int):
            return value
        model, _ = self._ensure_model_loaded()
        config = getattr(model, "config", None)
        candidate_maps = (
            ["relation_id2label", "relation_id_to_label", "id2label"]
            if relation
            else ["entity_id2label", "entity_id_to_label", "id2label"]
        )
        if config is not None:
            for attr in candidate_maps:
                mapping = getattr(config, attr, None)
                if isinstance(mapping, dict) and value in mapping:
                    return mapping[value]
                if isinstance(mapping, dict) and str(value) in mapping:
                    return mapping[str(value)]
            list_attr = "link_types" if relation else "entity_types"
            mapping = getattr(config, list_attr, None)
            if isinstance(mapping, list) and 0 <= value < len(mapping):
                return mapping[value]
        return value

    @staticmethod
    def _offset_span_text(
        text: str,
        offset_mapping: list[tuple[int, int]] | None,
        start: int | None,
        end: int | None,
        *,
        char_level: bool = False,
    ) -> str:
        if start is None or end is None:
            return ""
        if char_level:
            if 0 <= start < end <= len(text):
                return text[start:end].strip()
            return ""
        if not offset_mapping:
            return ""
        if start < 0 or start >= len(offset_mapping):
            return ""
        end_index = max(start, min(end - 1, len(offset_mapping) - 1))
        char_start = offset_mapping[start][0]
        char_end = offset_mapping[end_index][1]
        if char_start >= char_end:
            return ""
        return text[char_start:char_end].strip()

    def _looks_like_entity(self, item: Any) -> bool:
        if item is None:
            return False
        if isinstance(item, (dict,)):
            return any(
                key in item
                for key in (
                    "text",
                    "name",
                    "entity",
                    "label",
                    "type",
                    "tag",
                    "start",
                    "end",
                )
            )
        if isinstance(item, (list, tuple)):
            if len(item) in (2, 3):
                return True
            if (
                len(item) >= 4
                and isinstance(item[0], (list, tuple))
                and isinstance(item[1], int)
                and isinstance(item[2], str)
            ):
                return True
        return any(
            hasattr(item, name)
            for name in ("text", "name", "entity", "label", "type", "tag", "start", "end")
        )

    def _looks_like_relation(self, item: Any) -> bool:
        if item is None:
            return False
        if isinstance(item, dict):
            return any(
                key in item
                for key in ("head", "tail", "source", "target", "label", "relation", "type")
            )
        if isinstance(item, (list, tuple)):
            if len(item) == 3:
                return True
            return (
                len(item) >= 4
                and self._looks_like_entity(item[0])
                and isinstance(item[1], int)
                and self._looks_like_entity(item[2])
            )
        return any(
            hasattr(item, name)
            for name in ("head", "tail", "source", "target", "label", "relation", "type")
        )

    def _normalize_output_list(self, items: Any, *, relation: bool) -> list[Any]:
        if items is None:
            return []
        if isinstance(items, (list, tuple)):
            if len(items) == 1 and isinstance(items[0], (list, tuple)):
                checker = self._looks_like_relation if relation else self._looks_like_entity
                nested = list(items[0])
                if not nested or checker(nested[0]):
                    return nested
            checker = self._looks_like_relation if relation else self._looks_like_entity
            if items and checker(items[0]):
                return list(items)
            return list(items)
        return [items]

    def _parse_entity(
        self,
        entity: Any,
        *,
        text: str,
        offset_mapping: list[tuple[int, int]] | None,
    ) -> tuple[str, str]:
        entity_name = ""
        entity_type: Any = ""

        if isinstance(entity, (list, tuple)):
            if (
                len(entity) >= 4
                and isinstance(entity[0], (list, tuple))
                and isinstance(entity[1], int)
                and isinstance(entity[2], str)
            ):
                entity_name = entity[2]
                entity_type = entity[3]
            elif len(entity) >= 3 and isinstance(entity[0], str) and isinstance(entity[1], int) and isinstance(entity[2], int):
                entity_type = entity[0]
                entity_name = self._offset_span_text(text, offset_mapping, entity[1], entity[2] + 1)
            elif len(entity) >= 3 and isinstance(entity[0], int) and isinstance(entity[1], int):
                entity_name = self._offset_span_text(text, offset_mapping, entity[0], entity[1] + 1)
                entity_type = entity[2]
            elif len(entity) == 2 and all(isinstance(v, str) for v in entity):
                entity_name, entity_type = entity
        else:
            entity_name = self._normalize_text(
                self._maybe_attr(entity, "text", "name", "entity", "value", "mention", "surface")
            )
            entity_type = self._maybe_attr(
                entity,
                "label",
                "type",
                "tag",
                "entity_type",
                "entity_label",
            )

            if not entity_name:
                start_char = self._maybe_attr(
                    entity, "start_char", "char_start", "begin_char"
                )
                end_char = self._maybe_attr(entity, "end_char", "char_end", "stop_char")
                if isinstance(start_char, int) and isinstance(end_char, int):
                    entity_name = self._offset_span_text(
                        text,
                        offset_mapping,
                        start_char,
                        end_char,
                        char_level=True,
                    )
                else:
                    start = self._maybe_attr(entity, "start", "start_idx", "begin")
                    end = self._maybe_attr(entity, "end", "end_idx", "stop")
                    if isinstance(start, int) and isinstance(end, int):
                        entity_name = self._offset_span_text(
                            text,
                            offset_mapping,
                            start,
                            end + 1,
                        )

        entity_name = self._normalize_entity_name(entity_name)
        entity_type = self._lookup_label(entity_type, relation=False)
        return entity_name, self._normalize_entity_type(entity_type)

    def _resolve_endpoint_name(
        self,
        value: Any,
        *,
        entity_names: dict[int, str],
        text: str,
        offset_mapping: list[tuple[int, int]] | None,
    ) -> str:
        if value is None:
            return ""
        if isinstance(value, int):
            if value in entity_names:
                return entity_names[value]
            if (value - 1) in entity_names:
                return entity_names[value - 1]
            return ""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                idx = int(stripped)
                if idx in entity_names:
                    return entity_names[idx]
                if (idx - 1) in entity_names:
                    return entity_names[idx - 1]
            return self._normalize_entity_name(stripped)
        entity_name, _ = self._parse_entity(
            value,
            text=text,
            offset_mapping=offset_mapping,
        )
        return entity_name

    def _parse_relation(
        self,
        relation: Any,
        *,
        entity_names: dict[int, str],
        text: str,
        offset_mapping: list[tuple[int, int]] | None,
    ) -> tuple[str, str, str]:
        source = target = ""
        relation_type: Any = ""

        if isinstance(relation, (list, tuple)) and len(relation) >= 3:
            a, b, c = relation[:3]
            if self._looks_like_entity(a) and self._looks_like_entity(c):
                source, target, relation_type = (
                    self._resolve_endpoint_name(a, entity_names=entity_names, text=text, offset_mapping=offset_mapping),
                    self._resolve_endpoint_name(c, entity_names=entity_names, text=text, offset_mapping=offset_mapping),
                    b,
                )
            elif isinstance(a, int) and isinstance(b, int):
                source, target, relation_type = (
                    self._resolve_endpoint_name(a, entity_names=entity_names, text=text, offset_mapping=offset_mapping),
                    self._resolve_endpoint_name(b, entity_names=entity_names, text=text, offset_mapping=offset_mapping),
                    c,
                )
            elif isinstance(a, int) and isinstance(c, int):
                source, target, relation_type = (
                    self._resolve_endpoint_name(a, entity_names=entity_names, text=text, offset_mapping=offset_mapping),
                    self._resolve_endpoint_name(c, entity_names=entity_names, text=text, offset_mapping=offset_mapping),
                    b,
                )
            elif isinstance(a, str) and isinstance(c, str):
                source, target, relation_type = (
                    self._resolve_endpoint_name(a, entity_names=entity_names, text=text, offset_mapping=offset_mapping),
                    self._resolve_endpoint_name(c, entity_names=entity_names, text=text, offset_mapping=offset_mapping),
                    b,
                )
        else:
            source = self._resolve_endpoint_name(
                self._maybe_attr(
                    relation, "head", "source", "src", "from", "subject", "left", "entity1"
                ),
                entity_names=entity_names,
                text=text,
                offset_mapping=offset_mapping,
            )
            target = self._resolve_endpoint_name(
                self._maybe_attr(
                    relation, "tail", "target", "tgt", "to", "object", "right", "entity2"
                ),
                entity_names=entity_names,
                text=text,
                offset_mapping=offset_mapping,
            )
            relation_type = self._maybe_attr(
                relation,
                "label",
                "type",
                "relation",
                "tag",
                "rel_type",
            )

        relation_type = self._lookup_label(relation_type, relation=True)
        return source, target, self._relation_keywords(relation_type)

    def _annotation_to_chunk_result(
        self,
        generation_output: Any,
        *,
        text: str,
        offset_mapping: list[tuple[int, int]] | None,
        chunk_key: str,
        file_path: str,
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[tuple[str, str], list[dict[str, Any]]]]:
        timestamp = int(time.time())
        maybe_nodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        maybe_edges: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

        entities_raw = self._normalize_output_list(
            getattr(generation_output, "entities", None),
            relation=False,
        )
        links_raw = self._normalize_output_list(
            getattr(generation_output, "links", None),
            relation=True,
        )

        entity_names: dict[int, str] = {}
        parsed_entity_samples: list[dict[str, Any]] = []
        for idx, raw_entity in enumerate(entities_raw):
            entity_name, entity_type = self._parse_entity(
                raw_entity,
                text=text,
                offset_mapping=offset_mapping,
            )
            if len(parsed_entity_samples) < 3:
                parsed_entity_samples.append(
                    {
                        "raw": self._safe_repr(raw_entity, 300),
                        "entity_name": entity_name,
                        "entity_type": entity_type,
                    }
                )
            if not entity_name:
                continue
            maybe_nodes[entity_name].append(
                {
                    "entity_name": entity_name,
                    "entity_type": entity_type,
                    "description": self._entity_description(entity_name, entity_type),
                    "source_id": chunk_key,
                    "file_path": file_path,
                    "created_at": timestamp,
                }
            )
            entity_names[idx] = entity_name

        parsed_relation_samples: list[dict[str, Any]] = []
        for raw_relation in links_raw:
            source, target, relation_keywords = self._parse_relation(
                raw_relation,
                entity_names=entity_names,
                text=text,
                offset_mapping=offset_mapping,
            )
            if len(parsed_relation_samples) < 3:
                parsed_relation_samples.append(
                    {
                        "raw": self._safe_repr(raw_relation, 300),
                        "source": source,
                        "target": target,
                        "keywords": relation_keywords,
                    }
                )
            if not source or not target or source == target:
                continue
            edge_key = (source, target)
            maybe_edges[edge_key].append(
                {
                    "src_id": source,
                    "tgt_id": target,
                    "description": self._relation_description(source, relation_keywords, target),
                    "keywords": relation_keywords,
                    "source_id": chunk_key,
                    "weight": 1.0,
                    "file_path": file_path,
                    "created_at": timestamp,
                }
            )

        self._debug_log_output(
            text=text,
            generation_output=generation_output,
            entities_raw=entities_raw,
            links_raw=links_raw,
            parsed_entity_samples=parsed_entity_samples,
            parsed_relation_samples=parsed_relation_samples,
        )

        return dict(maybe_nodes), dict(maybe_edges)

    @staticmethod
    def _merge_chunk_results(
        chunk_results: list[
            tuple[
                dict[str, list[dict[str, Any]]],
                dict[tuple[str, str], list[dict[str, Any]]],
            ]
        ]
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[tuple[str, str], list[dict[str, Any]]]]:
        merged_nodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        merged_edges: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for maybe_nodes, maybe_edges in chunk_results:
            for entity_name, entity_records in maybe_nodes.items():
                merged_nodes[entity_name].extend(entity_records)
            for edge_key, edge_records in maybe_edges.items():
                merged_edges[edge_key].extend(edge_records)
        return dict(merged_nodes), dict(merged_edges)

    def _run_model(self, text: str):
        import torch

        model, tokenizer = self._ensure_model_loaded()
        encoded = tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=self.config.max_length,
            return_offsets_mapping=True,
        )
        offset_mapping = encoded.pop("offset_mapping", None)
        encoded = {
            key: value.to(self.config.device) if hasattr(value, "to") else value
            for key, value in encoded.items()
        }
        with torch.inference_mode():
            outputs = model.generate(
                encoded["input_ids"],
                attention_mask=encoded.get("attention_mask"),
            )
        if self.config.empty_cache_each_batch and torch.cuda.is_available():
            torch.cuda.empty_cache()
        offsets = offset_mapping[0].tolist() if offset_mapping is not None else None
        return outputs, offsets

    async def _extract_single_chunk(
        self,
        chunk_key: str,
        chunk_data: dict[str, Any],
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[tuple[str, str], list[dict[str, Any]]]]:
        file_path = chunk_data.get("file_path", "unknown_source")
        content = str(chunk_data.get("content", "") or "")
        segments = self._segment_text(content)

        if len(segments) > 1:
            logger.info(
                "ITER segmented chunk %s into %d spans to fit max_length=%d",
                chunk_key,
                len(segments),
                self.config.max_length,
            )
        elif self._token_length(content) > self.config.max_length:
            logger.warning(
                "ITER processing chunk %s without splitting although token length exceeds max_length=%d; input will be truncated",
                chunk_key,
                self.config.max_length,
            )

        all_results = []
        for segment in segments:
            generation_output, offset_mapping = await asyncio.to_thread(self._run_model, segment)
            all_results.append(
                self._annotation_to_chunk_result(
                    generation_output,
                    text=segment,
                    offset_mapping=offset_mapping,
                    chunk_key=chunk_key,
                    file_path=file_path,
                )
            )
            del generation_output
            gc.collect()

        return self._merge_chunk_results(all_results)

    async def extract_entities(
        self,
        chunks: dict[str, dict[str, Any]],
        global_config: dict[str, Any],
        pipeline_status: dict | None = None,
        pipeline_status_lock=None,
        llm_response_cache=None,
        text_chunks_storage=None,
    ) -> list:
        ordered_chunks = list(chunks.items())
        if not ordered_chunks:
            return []

        if pipeline_status is not None and pipeline_status_lock is not None:
            async with pipeline_status_lock:
                if pipeline_status.get("cancellation_requested", False):
                    raise RuntimeError("User cancelled during ITER extraction")

        results: list = []
        total = len(ordered_chunks)
        for index, (chunk_key, chunk_data) in enumerate(ordered_chunks, start=1):
            results.append(await self._extract_single_chunk(chunk_key, chunk_data))
            if pipeline_status is not None and pipeline_status_lock is not None:
                async with pipeline_status_lock:
                    pipeline_status["latest_message"] = (
                        f"ITER extracted entities for {index}/{total} chunks"
                    )
                    pipeline_status["history_messages"].append(
                        pipeline_status["latest_message"]
                    )

        logger.info("ITER extracted entities for %d chunks", total)
        return results


class ITERADEExtractionPatch:
    """Temporarily replaces LightRAG extraction with ITER extraction."""

    def __init__(self, config: ITERADEConfig):
        self.extractor = ITERADEExtractor(config)
        self._installed = False
        self._originals: list[tuple[Any, str, Any]] = []

    def validate(self) -> None:
        self.extractor.validate()

    def install(self) -> None:
        if self._installed:
            return

        import lightrag.lightrag as lightrag_module
        import lightrag.operate as operate_module
        import raganything.modalprocessors as modalprocessors_module

        patched_extract = self.extractor.extract_entities
        targets = [
            (operate_module, "extract_entities"),
            (lightrag_module, "extract_entities"),
            (modalprocessors_module, "extract_entities"),
        ]
        for module, attr_name in targets:
            self._originals.append((module, attr_name, getattr(module, attr_name)))
            setattr(module, attr_name, patched_extract)

        self._installed = True
        logger.info("Installed ITER extraction patch")

    def restore(self) -> None:
        if not self._installed:
            return
        while self._originals:
            module, attr_name, original_value = self._originals.pop()
            setattr(module, attr_name, original_value)
        self._installed = False
        logger.info("Restored original LightRAG extraction backend")

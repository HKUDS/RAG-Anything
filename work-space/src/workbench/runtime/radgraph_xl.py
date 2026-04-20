from __future__ import annotations

import asyncio
import gc
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

logger = logging.getLogger("RadGraphXL")


@dataclass
class RadGraphXLConfig:
    model_type: str = "modern-radgraph-xl"
    batch_size: int = 1
    cuda_device: int = 0
    split_chunks: bool = False
    max_segment_chars: int = 1400
    sentence_overlap: int = 1
    empty_cache_each_batch: bool = True


class RadGraphXLExtractor:
    """Adapter that mimics LightRAG extract_entities(...) with RadGraph-XL."""

    def __init__(self, config: RadGraphXLConfig):
        self.config = config
        self._model = None

    def validate(self) -> None:
        self._ensure_model_loaded()

    def _ensure_model_loaded(self):
        if self._model is not None:
            return self._model

        try:
            from radgraph import RadGraph
        except ImportError as exc:
            raise RuntimeError(
                "RadGraph-XL backend requires the `radgraph` package. "
                "Install it in the benchmark environment first, e.g. "
                "`/mnt/disk1/aiotlab/envs/raganything/bin/pip install radgraph`."
            ) from exc

        logger.info(
            "Loading RadGraph model_type=%s on cuda:%s",
            self.config.model_type,
            self.config.cuda_device,
        )
        self._model = RadGraph(
            model_type=self.config.model_type,
            batch_size=max(1, int(self.config.batch_size)),
            cuda=int(self.config.cuda_device),
        )
        return self._model

    def _run_model(self, texts: list[str]):
        import torch

        model = self._ensure_model_loaded()
        with torch.inference_mode():
            outputs = model(texts)
        if self.config.empty_cache_each_batch and torch.cuda.is_available():
            torch.cuda.empty_cache()
        return outputs

    @staticmethod
    def _normalize_text(value: Any) -> str:
        if value is None:
            return ""
        text = " ".join(str(value).strip().split())
        return text.strip().strip('"').strip("'")

    @classmethod
    def _normalize_entity_name(cls, value: Any) -> str:
        text = cls._normalize_text(value)
        return text[:255]

    @classmethod
    def _normalize_entity_type(cls, label: str) -> str:
        if not label:
            return "unknown"
        prefix = label.split("::", 1)[0]
        normalized = cls._normalize_text(prefix).replace(" ", "_").lower()
        return normalized or "unknown"

    @classmethod
    def _entity_description(cls, entity_name: str, label: str) -> str:
        label = cls._normalize_text(label)
        if not label:
            return entity_name
        return f"{entity_name} [{label}]"

    @classmethod
    def _relation_keywords(cls, relation_type: Any) -> str:
        normalized = cls._normalize_text(relation_type).replace(" ", "_").lower()
        return normalized or "related_to"

    @classmethod
    def _relation_description(
        cls, source: str, relation_type: Any, target: str
    ) -> str:
        rel = cls._relation_keywords(relation_type)
        return f"{source} {rel} {target}"

    @staticmethod
    def _iter_entity_relations(entity_data: dict[str, Any]) -> Iterable[tuple[str, str]]:
        relations = entity_data.get("relations") or []
        for relation in relations:
            if isinstance(relation, (list, tuple)) and len(relation) >= 2:
                yield str(relation[0]), str(relation[1])

    @staticmethod
    def _annotation_for_index(annotations: Any, index: int) -> dict[str, Any]:
        if isinstance(annotations, list):
            if 0 <= index < len(annotations):
                return annotations[index] or {}
            return {}
        if isinstance(annotations, dict):
            return annotations.get(str(index)) or annotations.get(index) or {}
        return {}

    @classmethod
    def _sentence_units(cls, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []
        units = [
            unit.strip()
            for unit in re.split(r"(?<=[\.\!\?\:\;])\s+|\n{2,}", text)
            if unit and unit.strip()
        ]
        return units or [text]

    @classmethod
    def _split_long_unit(cls, unit: str, max_chars: int) -> list[str]:
        words = unit.split()
        if not words:
            return []
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for word in words:
            candidate_len = current_len + len(word) + (1 if current else 0)
            if current and candidate_len > max_chars:
                chunks.append(" ".join(current))
                overlap = current[-20:] if len(current) > 20 else current[-5:]
                current = list(overlap) + [word]
                current_len = len(" ".join(current))
            else:
                current.append(word)
                current_len = candidate_len
        if current:
            chunks.append(" ".join(current))
        return chunks

    def _segment_text(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []
        if not self.config.split_chunks:
            return [text]
        if len(text) <= self.config.max_segment_chars:
            return [text]

        units = self._sentence_units(text)
        segments: list[str] = []
        current_units: list[str] = []
        current_len = 0

        def flush():
            nonlocal current_units, current_len
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
            current_len = len(" ".join(current_units))

        for unit in units:
            if len(unit) > self.config.max_segment_chars:
                if current_units:
                    flush()
                for split_unit in self._split_long_unit(unit, self.config.max_segment_chars):
                    segments.append(split_unit)
                current_units = []
                current_len = 0
                continue

            candidate_len = current_len + len(unit) + (1 if current_units else 0)
            if current_units and candidate_len > self.config.max_segment_chars:
                flush()

            current_units.append(unit)
            current_len = len(" ".join(current_units))

        if current_units:
            flush()

        return segments or [text]

    def _annotation_to_chunk_result(
        self, annotation: dict[str, Any], chunk_key: str, file_path: str
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[tuple[str, str], list[dict[str, Any]]]]:
        timestamp = int(time.time())
        maybe_nodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        maybe_edges: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

        entities = annotation.get("entities") or {}
        entity_id_to_name: dict[str, str] = {}

        for entity_id, entity_data in entities.items():
            entity_name = self._normalize_entity_name(entity_data.get("tokens"))
            if not entity_name:
                continue

            label = self._normalize_text(entity_data.get("label"))
            entity_record = {
                "entity_name": entity_name,
                "entity_type": self._normalize_entity_type(label),
                "description": self._entity_description(entity_name, label),
                "source_id": chunk_key,
                "file_path": file_path,
                "created_at": timestamp,
            }
            maybe_nodes[entity_name].append(entity_record)
            entity_id_to_name[str(entity_id)] = entity_name

        for entity_id, entity_data in entities.items():
            source_name = entity_id_to_name.get(str(entity_id))
            if not source_name:
                continue

            for relation_type, target_entity_id in self._iter_entity_relations(entity_data):
                target_name = entity_id_to_name.get(str(target_entity_id))
                if not target_name or target_name == source_name:
                    continue
                edge_key = (source_name, target_name)
                maybe_edges[edge_key].append(
                    {
                        "src_id": source_name,
                        "tgt_id": target_name,
                        "description": self._relation_description(
                            source_name, relation_type, target_name
                        ),
                        "keywords": self._relation_keywords(relation_type),
                        "source_id": chunk_key,
                        "weight": 1.0,
                        "file_path": file_path,
                        "created_at": timestamp,
                    }
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

    async def _extract_single_chunk(
        self,
        chunk_key: str,
        chunk_data: dict[str, Any],
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[tuple[str, str], list[dict[str, Any]]]]:
        file_path = chunk_data.get("file_path", "unknown_source")
        content = chunk_data.get("content", "")
        segments = self._segment_text(content)

        if len(segments) > 1:
            logger.info(
                "RadGraph segmented chunk %s into %d spans to reduce VRAM",
                chunk_key,
                len(segments),
            )

        all_results = []
        batch_size = max(1, int(self.config.batch_size))
        for start in range(0, len(segments), batch_size):
            batch_segments = segments[start : start + batch_size]
            annotations = await asyncio.to_thread(self._run_model, batch_segments)
            for local_index in range(len(batch_segments)):
                annotation = self._annotation_for_index(annotations, local_index)
                all_results.append(
                    self._annotation_to_chunk_result(annotation, chunk_key, file_path)
                )
            del annotations
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
                    raise RuntimeError("User cancelled during RadGraph extraction")

        results: list = []
        total = len(ordered_chunks)
        for index, (chunk_key, chunk_data) in enumerate(ordered_chunks, start=1):
            results.append(await self._extract_single_chunk(chunk_key, chunk_data))
            if pipeline_status is not None and pipeline_status_lock is not None:
                async with pipeline_status_lock:
                    pipeline_status["latest_message"] = (
                        f"RadGraph extracted entities for {index}/{total} chunks"
                    )
                    pipeline_status["history_messages"].append(
                        pipeline_status["latest_message"]
                    )

        logger.info("RadGraph extracted entities for %d chunks", total)
        return results


class RadGraphXLExtractionPatch:
    """Temporarily replaces LightRAG extraction with RadGraph-XL extraction."""

    def __init__(self, config: RadGraphXLConfig):
        self.extractor = RadGraphXLExtractor(config)
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
        logger.info("Installed RadGraph-XL extraction patch")

    def restore(self) -> None:
        if not self._installed:
            return
        while self._originals:
            module, attr_name, original_value = self._originals.pop()
            setattr(module, attr_name, original_value)
        self._installed = False
        logger.info("Restored original LightRAG extraction backend")

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable

logger = logging.getLogger("RadGraphXL")


@dataclass
class RadGraphXLConfig:
    model_type: str = "modern-radgraph-xl"
    batch_size: int = 8


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
            "Loading RadGraph model_type=%s",
            self.config.model_type,
        )
        self._model = RadGraph(model_type=self.config.model_type)
        return self._model

    def _run_model(self, texts: list[str]):
        model = self._ensure_model_loaded()
        return model(texts)

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
        batch_size = max(1, int(self.config.batch_size))
        total = len(ordered_chunks)

        for start in range(0, total, batch_size):
            batch = ordered_chunks[start : start + batch_size]
            texts = [chunk_data.get("content", "") for _, chunk_data in batch]
            annotations = await asyncio.to_thread(self._run_model, texts)

            for local_index, (chunk_key, chunk_data) in enumerate(batch):
                annotation = self._annotation_for_index(annotations, local_index)
                file_path = chunk_data.get("file_path", "unknown_source")
                results.append(
                    self._annotation_to_chunk_result(annotation, chunk_key, file_path)
                )

            if pipeline_status is not None and pipeline_status_lock is not None:
                async with pipeline_status_lock:
                    done = min(start + len(batch), total)
                    pipeline_status["latest_message"] = (
                        f"RadGraph extracted entities for {done}/{total} chunks"
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

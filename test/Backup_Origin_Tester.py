#!/usr/bin/env python
"""
ScienceQA tester that mirrors the structure of the reference benchmark script
while wiring in RAG-Anything for optional retrieval-augmented reasoning.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import logging.config
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from collections import Counter, defaultdict
import numpy as np
from tqdm import tqdm

# Add project root directory to Python path (same pattern as other examples)
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from dotenv import load_dotenv

from lightrag.llm.azure_openai import azure_openai_complete_if_cache, azure_openai_embed
from lightrag.utils import EmbeddingFunc, logger, set_verbose_debug
from lightrag import QueryParam

from raganything import RAGAnything, RAGAnythingConfig


load_dotenv(dotenv_path=".env", override=False)


CHOICE_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DEFAULT_SYSTEM_PROMPT = (
    "You are a careful science tutor. Think step by step and return only the letter of the best answer."
)


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, separator: str = ",") -> List[str]:
    value = os.getenv(name, "")
    return [item.strip().lower() for item in value.split(separator) if item.strip()]


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _azure_api_kwargs() -> Dict[str, str]:
    api_version = os.getenv("AZURE_OPENAI_API_VERSION") or os.getenv("OPENAI_API_VERSION")
    return {"api_version": api_version} if api_version else {}


def _http_post_json(url: str, payload: dict, timeout: int = 240) -> dict:
    """Minimal helper to POST JSON without external deps (shared with example scripts)."""
    import urllib.error
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code} error from {url}: {body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to reach {url}: {e}")


def _build_ollama_embedding_func() -> EmbeddingFunc:
    host = os.getenv("EMBEDDING_BINDING_HOST", os.getenv("LLM_BINDING_HOST", "http://127.0.0.1:11434")).rstrip("/")
    model = os.getenv("EMBEDDING_MODEL", "bge-m3:latest").strip()
    url = f"{host}/api/embeddings"
    timeout = _env_int("TIMEOUT", 240)
    max_concurrency = max(1, _env_int("EMBEDDING_MAX_CONCURRENCY", 4))
    semaphore = asyncio.Semaphore(max_concurrency)

    async def embed_batch(texts: Iterable[str]) -> List[List[float]]:
        async def one(text: str) -> List[float]:
            payload = {"model": model, "prompt": text}
            async with semaphore:
                resp = await asyncio.to_thread(_http_post_json, url, payload, timeout)
            embedding = resp.get("embedding")
            if not embedding:
                raise RuntimeError("No embedding returned from Ollama")
            return embedding

        if not texts:
            return []
        return list(await asyncio.gather(*(one(t) for t in texts)))

    dim = os.getenv("EMBEDDING_DIM")
    embedding_dim = int(dim) if dim and dim.isdigit() else None
    return EmbeddingFunc(
        embedding_dim=embedding_dim or 1024,
        max_token_size=_env_int("MAX_EMBED_TOKENS", 8192),
        func=embed_batch,
    )


def configure_logging() -> None:
    """Match the logging setup used in the example script."""
    log_dir = os.getenv("LOG_DIR", os.getcwd())
    log_file = os.path.abspath(os.path.join(log_dir, "scienceqa_tester.log"))
    print(f"\nScienceQA tester log file: {log_file}\n")
    os.makedirs(os.path.dirname(log_dir), exist_ok=True)

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {"format": "%(levelname)s: %(message)s"},
                "detailed": {"format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "stream": "ext://sys.stderr",
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "detailed",
                    "filename": log_file,
                    "maxBytes": int(os.getenv("LOG_MAX_BYTES", 10_485_760)),
                    "backupCount": int(os.getenv("LOG_BACKUP_COUNT", 5)),
                    "encoding": "utf-8",
                },
            },
            "loggers": {
                "lightrag": {
                    "handlers": ["console", "file"],
                    "level": "INFO",
                    "propagate": False,
                },
            },
        }
    )
    logger.setLevel(logging.INFO)
    set_verbose_debug(os.getenv("VERBOSE", "false").lower() == "true")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ScienceQA tester using RAG-Anything")
    parser.add_argument("--data_root", type=str, help="Root folder containing problems.json and pid_splits.json")
    parser.add_argument("--problems_json", type=str, help="Optional explicit path to problems.json")
    parser.add_argument("--split_json", type=str, help="Optional explicit path to pid_splits.json or split list")
    parser.add_argument("--image_root", type=str, help="Directory containing question images")
    parser.add_argument("--caption_file", type=str, help="Optional captions JSON file")
    parser.add_argument("--model", type=str, default=os.getenv("LLM_MODEL", "gpt-4o-mini"))
    parser.add_argument("--options", nargs="*", default=list("ABCDE"))
    parser.add_argument("--prompt_format", type=str, default="CQM-A")
    parser.add_argument("--test_split", type=str, default="test", choices=["train", "val", "minival", "test"])
    parser.add_argument("--test_number", type=int, default=-1)
    parser.add_argument("--shot_number", type=int, default=0)
    parser.add_argument("--shot_qids", nargs="*", default=None)
    parser.add_argument("--save_every", type=int, default=50)
    parser.add_argument("--label", type=str, default="scienceqa_rag")
    parser.add_argument("--output_root", type=str, default="./output/scienceqa")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--force_text", action="store_true")
    parser.add_argument("--use_caption", action="store_true")

    parser.add_argument("--working_dir", type=str, default=os.getenv("WORKING_DIR", "./rag_storage"))
    parser.add_argument("--rag_output", type=str, default=os.getenv("OUTPUT_DIR", "./rag_output"))
    parser.add_argument("--knowledge_dir", type=str, help="Directory of documents to ingest before evaluation")
    parser.add_argument("--knowledge_recursive", action="store_true")
    parser.add_argument("--supported_exts", type=str, default=os.getenv("SUPPORTED_FILE_EXTENSIONS", ""))
    parser.add_argument("--mode", type=str, default=os.getenv("MODE", "hybrid"))
    parser.add_argument("--top_k", type=int, default=_env_int("TOP_K", _env_int("SCIENCEQA_RAG_TOP_K", 4)))
    parser.add_argument("--rate_limit_delay", type=float, default=_env_float("SCIENCEQA_RATE_LIMIT_DELAY", 1.0))
    parser.add_argument("--rate_limit_retries", type=int, default=_env_int("SCIENCEQA_RATE_LIMIT_RETRIES", 6))
    parser.add_argument("--rate_limit_backoff", type=float, default=_env_float("SCIENCEQA_RATE_LIMIT_BACKOFF", 2.0))

    parser.add_argument("--openai_key", type=str, default=os.getenv("LLM_BINDING_KEY"), help="Override API key (defaults to .env)")
    parser.add_argument("--base_url", type=str, default=os.getenv("LLM_BINDING_HOST"))
    parser.add_argument("--engine", type=str, default=os.getenv("LLM_MODEL"))
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--max_tokens", type=int, default=os.getenv("MAX_TOKENS"))
    parser.add_argument("--dry_run", action="store_true")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_dataset_paths(args: argparse.Namespace) -> Tuple[Path, Path]:
    problems_path = Path(args.problems_json).expanduser() if args.problems_json else None
    splits_path = Path(args.split_json).expanduser() if args.split_json else None

    data_root = Path(args.data_root).expanduser() if args.data_root else None
    if data_root:
        if not problems_path:
            candidate = data_root / "problems.json"
            if candidate.exists():
                problems_path = candidate
        if not splits_path:
            candidate = data_root / "pid_splits.json"
            if candidate.exists():
                splits_path = candidate

    if not problems_path:
        fallback = ROOT_DIR / "Dataset" / "ScienceQA" / "data" / "scienceqa" / "problems.json"
        if fallback.exists():
            problems_path = fallback
    if not splits_path and problems_path:
        candidate = problems_path.parent / "pid_splits.json"
        if candidate.exists():
            splits_path = candidate

    if not problems_path or not problems_path.exists():
        raise FileNotFoundError("problems.json not found. Specify --problems_json or --data_root.")
    if not splits_path or not splits_path.exists():
        raise FileNotFoundError("pid_splits.json not found. Specify --split_json or --data_root.")
    return problems_path, splits_path


def load_data(args: argparse.Namespace) -> Tuple[Dict[str, Any], List[str], List[str], Dict[str, List[str]]]:
    problems_path, splits_path = _resolve_dataset_paths(args)
    problems_raw = _load_json(problems_path)
    problems: Dict[str, Any] = {str(k): v for k, v in problems_raw.items()}

    captions = {}
    if args.caption_file:
        caption_path = Path(args.caption_file).expanduser()
        if caption_path.exists():
            cap_data = _load_json(caption_path)
            captions = cap_data.get("captions", cap_data) if isinstance(cap_data, dict) else {}
    for qid, problem in problems.items():
        if qid in captions:
            problem["caption"] = captions[qid]

    splits = _load_json(splits_path)
    split_qids: Dict[str, List[str]] = {}

    def _normalize_split_ids(raw_ids: Any) -> List[str]:
        if isinstance(raw_ids, dict):
            candidates = raw_ids.get("qids") or list(raw_ids.values())
        else:
            candidates = raw_ids

        if not isinstance(candidates, Iterable) or isinstance(candidates, (str, bytes)):
            return []

        normalized: List[str] = []
        for item in candidates:
            if isinstance(item, Iterable) and not isinstance(item, (str, bytes)):
                normalized.extend(_normalize_split_ids(item))
            else:
                qid = str(item)
                if qid in problems:
                    normalized.append(qid)
        return normalized

    if isinstance(splits, dict):
        for split_name, raw_ids in splits.items():
            normalized_ids = _normalize_split_ids(raw_ids)
            if normalized_ids:
                split_qids[split_name] = list(dict.fromkeys(normalized_ids))
    else:
        normalized_ids = _normalize_split_ids(splits)
        if normalized_ids:
            split_qids[args.test_split] = list(dict.fromkeys(normalized_ids))

    problem_split_map: Dict[str, List[str]] = defaultdict(list)
    for qid, problem in problems.items():
        split_name = str(problem.get("split") or "").strip().lower()
        if split_name:
            problem_split_map[split_name].append(qid)

    for split_name, ids in problem_split_map.items():
        filtered = [qid for qid in ids if qid in problems]
        if not filtered:
            continue
        existing = split_qids.get(split_name, [])
        merged = list(dict.fromkeys(existing + filtered))
        split_qids[split_name] = merged

    if args.test_split in split_qids:
        qids = list(split_qids[args.test_split])
    else:
        qids = []
    if args.test_number > 0:
        qids = qids[: args.test_number]
    print(f"number of test problems: {len(qids)}\n")

    shot_qids: List[str]
    if args.shot_qids:
        shot_qids = [str(qid) for qid in args.shot_qids]
        for qid in shot_qids:
            if qid not in split_qids.get("train", []):
                raise ValueError(f"Shot qid {qid} not found in train split.")
    else:
        if args.shot_number < 0 or args.shot_number > 32:
            raise ValueError("shot_number must be between 0 and 32.")
        train_qids = split_qids.get("train", [])
        if args.shot_number > 0 and len(train_qids) < args.shot_number:
            raise ValueError("Not enough train qids available to sample shots.")
        shot_qids = random.sample(train_qids, args.shot_number) if args.shot_number > 0 else []
    print("training question ids for prompting:", shot_qids, "\n")

    return problems, qids, shot_qids, split_qids


def _candidate_image_dirs(qid: str, image_root: Optional[Path], problem: Dict[str, Any]) -> List[Path]:
    dirs: List[Path] = []
    if image_root:
        dirs.append(image_root)

    split = (problem.get("split") or "").lower()
    dataset_root = ROOT_DIR / "Dataset" / "ScienceQA"
    if split:
        dirs.append(dataset_root / split)

    # Common fallbacks
    dirs.extend(
        [
            dataset_root / "test",
            dataset_root / "train",
            dataset_root / "val",
            dataset_root / "minival",
        ]
    )

    expanded: List[Path] = []
    try:
        qid_int = int(qid)
    except (TypeError, ValueError):
        qid_int = None
    for base in dirs:
        expanded.append(base / qid)
        if qid_int is not None:
            expanded.append(base / f"{qid_int:05d}")
        expanded.append(base)
    return expanded


def _resolve_image_path(problem: Dict[str, Any], image_root: Optional[Path], qid: str) -> Optional[Path]:
    candidates: List[Path] = []
    for key in ("image_path", "image", "image_id", "image_filename"):
        value = problem.get(key)
        if value:
            candidates.append(Path(str(value)))

    for extra in problem.get("image_choices", []):
        candidates.append(Path(str(extra)))

    search_bases = _candidate_image_dirs(qid, image_root, problem)

    # Direct absolute references
    for candidate in candidates:
        if candidate.is_absolute() and candidate.exists():
            return candidate

    for base in search_bases:
        for candidate in candidates:
            if base.is_dir():
                candidate_path = base / candidate
            else:
                candidate_path = base
            if candidate_path.is_dir():
                for default_name in ("image.png", "image.jpg", "image.jpeg"):
                    fallback = candidate_path / default_name
                    if fallback.exists():
                        return fallback
            elif candidate_path.exists():
                return candidate_path

        if base.is_dir():
            for default_name in ("image.png", "image.jpg", "image.jpeg"):
                fallback = base / default_name
                if fallback.exists():
                    return fallback

    return None


def _encode_image_to_base64(path: Path) -> Optional[Tuple[str, str]]:
    import mimetypes

    try:
        with path.open("rb") as f:
            payload = base64.b64encode(f.read()).decode("utf-8")
        mime, _ = mimetypes.guess_type(str(path))
        if not mime:
            mime = "image/png"
        return payload, mime
    except Exception:
        return None


def _format_choice_block(problem: Dict[str, Any], letters: List[str]) -> List[str]:
    choices = problem.get("choices") or []
    lines: List[str] = []
    for idx, choice in enumerate(choices):
        letter = letters[idx] if idx < len(letters) else CHOICE_LETTERS[idx % len(CHOICE_LETTERS)]
        lines.append(f"{letter}. {choice}")
    return lines


def _build_shot_section(problems: Dict[str, Any], shot_qids: List[str], use_caption: bool) -> Optional[str]:
    if not shot_qids:
        return None
    sections: List[str] = []
    for shot_id in shot_qids:
        if shot_id not in problems:
            continue
        shot = problems[shot_id]
        letters = list(CHOICE_LETTERS[: len(shot.get("choices", []))])
        question = shot.get("question", "").strip()
        answer = shot.get("answer")
        if isinstance(answer, int) and answer < len(letters):
            answer_letter = letters[answer]
        elif isinstance(answer, str):
            answer_letter = answer.strip().upper()
        else:
            answer_letter = ""
        block = ["Example Question:", question]
        block.extend(_format_choice_block(shot, letters))
        if use_caption and shot.get("caption"):
            block.append(f"Caption: {shot['caption']}")
        if answer_letter:
            block.append(f"Correct Answer: {answer_letter}")
        sections.append("\n".join(block))
    if not sections:
        return None
    return "\n\n".join(sections)


def _build_prompt(
    problem: Dict[str, Any],
    context: Optional[str],
    shot_context: Optional[str],
    include_caption: bool,
) -> Tuple[str, List[str]]:
    letters = list(CHOICE_LETTERS[: len(problem.get("choices", []))])
    lines: List[str] = []
    if shot_context:
        lines.append("Few-shot exemplars:")
        lines.append(shot_context.strip())
        lines.append("")
    if context:
        lines.append("Retrieved context:")
        lines.append(context.strip())
        lines.append("")

    question = problem.get("question", "").strip()
    if problem.get("hint"):
        question = f"{question}\nHint: {problem['hint']}"
    lines.append("Question:")
    lines.append(question)
    lines.append("")

    lines.extend(_format_choice_block(problem, letters))

    if include_caption and problem.get("caption"):
        lines.append("")
        lines.append(f"Image caption: {problem['caption']}")

    lines.append("")
    lines.append("Return only the single best answer letter.")
    return "\n".join(lines).strip(), letters


def _normalize_letter(text: str, valid_letters: List[str]) -> Optional[str]:
    candidate = (text or "").upper()
    for letter in valid_letters:
        if letter in candidate:
            return letter
    for char in candidate:
        if char in valid_letters:
            return char
    return None


async def _retrieve_context(
    rag: RAGAnything,
    question: str,
    mode: str,
    top_k: int,
) -> Optional[str]:
    if not getattr(rag, "lightrag", None):
        return None
    param = QueryParam(mode=mode, chunk_top_k=top_k, only_need_context=True)
    try:
        context = await rag.lightrag.aquery(question, param=param)
        return context.strip() if context else None
    except Exception as exc:
        logger.warning(f"Context retrieval failed: {exc}")
        return None


async def _ingest_knowledge(
    rag: RAGAnything,
    knowledge_dir: Path,
    output_dir: Path,
    recursive: bool,
    supported_exts: List[str],
) -> None:
    if not knowledge_dir.exists():
        raise FileNotFoundError(f"Knowledge directory does not exist: {knowledge_dir}")

    if recursive:
        files = [p for p in knowledge_dir.rglob("*") if p.is_file()]
    else:
        files = [p for p in knowledge_dir.iterdir() if p.is_file()]

    if supported_exts:
        lowered = {f".{ext.lstrip('.').lower()}" for ext in supported_exts}
        files = [f for f in files if f.suffix.lower() in lowered]

    if not files:
        raise FileNotFoundError(f"No ingestible files found in {knowledge_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    for file_path in files:
        logger.info(f"Ingesting knowledge document: {file_path}")
        await rag.process_document_complete(
            file_path=str(file_path),
            output_dir=str(output_dir),
            parse_method=rag.config.parse_method,
            device="cpu",
        )


async def _ingest_problem_metadata(
    rag: Optional[RAGAnything],
    problems: Dict[str, Any],
    qids: List[str],
    image_root: Optional[Path],
) -> None:
    """Insert question metadata (text + optional image) into LightRAG as structured content."""
    if not rag:
        return

    init_result = await rag._ensure_lightrag_initialized()
    if isinstance(init_result, dict) and init_result.get("success") is False:
        logger.warning(f"Failed to initialize LightRAG for metadata ingestion: {init_result.get('error')}")
        return

    lightrag = getattr(rag, "lightrag", None)
    if not lightrag:
        return

    for qid in qids:
        problem = problems[qid]

        content_list: List[Dict[str, Any]] = []
        page_idx = 0
        handled_keys = set()

        def _add_text_block(label: str, text: str) -> None:
            nonlocal page_idx
            text = text.strip()
            if not text:
                return
            prefix = f"{label}: " if label else ""
            content_list.append(
                {
                    "type": "text",
                    "text": f"{prefix}{text}",
                    "page_idx": page_idx,
                }
            )
            page_idx += 1

        question = (problem.get("question") or "").strip()
        if question:
            _add_text_block("Question", f"[{qid}] {question}")
            handled_keys.add("question")

        choices = problem.get("choices") or []
        if choices:
            formatted_choices = "\n".join(f"{CHOICE_LETTERS[idx]}. {choice}" for idx, choice in enumerate(choices))
            _add_text_block("Choices", formatted_choices)
            handled_keys.add("choices")

        if "answer" in problem:
            handled_keys.add("answer")

        metadata_pairs = [
            ("Split", "split"),
            ("Task", "task"),
            ("Grade", "grade"),
            ("Subject", "subject"),
            ("Topic", "topic"),
            ("Category", "category"),
            ("Skill", "skill"),
            ("Image Choice", "image_choice"),
        ]
        for label, key in metadata_pairs:
            value = problem.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                text_value = value.strip()
                if not text_value:
                    continue
            elif isinstance(value, (list, dict)):
                if not value:
                    continue
                text_value = json.dumps(value, ensure_ascii=False)
            else:
                text_value = str(value)
            _add_text_block(label, text_value)
            handled_keys.add(key)

        hint = (problem.get("hint") or "").strip()
        if hint:
            _add_text_block("Hint", hint)
            handled_keys.add("hint")

        lecture = (problem.get("lecture") or "").strip()
        if lecture:
            _add_text_block("Lecture", lecture)
            handled_keys.add("lecture")

        solution = (problem.get("solution") or "").strip()
        if solution:
            _add_text_block("Solution", solution)
            handled_keys.add("solution")

        for label, key in [
            ("Context", "context"),
            ("Explanation", "explanation"),
            ("Background", "background"),
            ("Rationale", "rationale"),
            ("Fact", "fact"),
            ("Additional Notes", "notes"),
        ]:
            value = problem.get(key)
            if not value:
                continue
            if isinstance(value, str):
                text_value = value.strip()
            else:
                try:
                    text_value = json.dumps(value, ensure_ascii=False)
                except TypeError:
                    text_value = str(value)
            if not text_value:
                continue
            _add_text_block(label, text_value)
            handled_keys.add(key)

        caption = (problem.get("caption") or "").strip()
        handled_keys.add("caption")
        image_path: Optional[Path] = None
        try:
            image_path = _resolve_image_path(problem, image_root, qid)
        except Exception as exc:
            logger.warning(f"Failed to resolve image for question {qid}: {exc}")
            image_path = None

        if image_path and image_path.exists():
            content_list.append(
                {
                    "type": "image",
                    "img_path": str(image_path.resolve()),
                    "img_caption": [caption] if caption else [],
                    "img_footnote": [],
                    "page_idx": page_idx,
                }
            )
            page_idx += 1
            handled_keys.update({"image", "image_path", "image_id", "image_filename"})

        remaining = {k: v for k, v in problem.items() if k not in handled_keys}
        if remaining:
            try:
                serialized = json.dumps(remaining, ensure_ascii=False, indent=2, sort_keys=True)
            except TypeError:
                serialized = str(remaining)
            _add_text_block("Raw Metadata", serialized)

        if not content_list:
            continue

        doc_id = f"sqa_meta_{qid}"
        try:
            await rag.insert_content_list(
                content_list=content_list,
                file_path=f"scienceqa_question_{qid}",
                doc_id=doc_id,
                display_stats=False,
            )
        except Exception as exc:
            logger.warning(f"Failed to insert metadata doc {doc_id}: {exc}")


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    if any(keyword in text for keyword in ("rate limit", "too many requests", "quota", "retry-after", "please retry")):
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    if status == 429:
        return True
    return False


def _extract_retry_after(exc: Exception) -> Optional[float]:
    for attr in ("retry_after", "retry_after_seconds", "retry_after_ms"):
        value = getattr(exc, attr, None)
        if value:
            try:
                seconds = float(value) / (1000 if attr.endswith("_ms") else 1)
                if seconds > 0:
                    return seconds
            except (TypeError, ValueError):
                continue

    headers = getattr(exc, "headers", None) or getattr(exc, "response_headers", None)
    if isinstance(headers, dict):
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if retry_after:
            try:
                return float(retry_after)
            except (TypeError, ValueError):
                pass

    text = str(exc)
    match = re.search(r"retry[- ]after[^0-9]*([0-9]+)", text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            pass

    match = re.search(r"try again in[^0-9]*([0-9]+)", text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            pass
    return None


async def run_scienceqa(
    args: argparse.Namespace,
    problems: Dict[str, Any],
    qids: List[str],
    shot_qids: List[str],
    split_qids: Dict[str, List[str]],
) -> None:
    api_key = (args.openai_key or os.getenv("LLM_BINDING_API_KEY") or "").strip()
    if not api_key and not args.dry_run:
        raise RuntimeError("API key is required. Set LLM_BINDING_API_KEY in .env or pass --openai_key.")
    base_url = (args.base_url or "").strip() or None
    llm_model = args.engine or args.model or os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("LLM_MODEL", "gpt-4o-mini")
    vision_model = os.getenv("AZURE_OPENAI_VISION_DEPLOYMENT") or os.getenv("VISION_MODEL") or "gpt-4o"
    embedding_model = os.getenv("AZURE_EMBEDDING_DEPLOYMENT") or os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")

    temperature = args.temperature if args.temperature is not None else _env_float("TEMPERATURE", 0.2)
    max_tokens = args.max_tokens if args.max_tokens is not None else _env_int("LLM_COMPLETION_MAX_TOKENS", 512)

    embedding_binding = os.getenv("EMBEDDING_BINDING", "").strip().lower()
    if embedding_binding == "ollama":
        embedding_func = _build_ollama_embedding_func()
    else:
        embedding_func = EmbeddingFunc(
            embedding_dim=_env_int("EMBEDDING_DIM", 3072),
            max_token_size=_env_int("MAX_EMBED_TOKENS", 8192),
            func=lambda texts: azure_openai_embed(
                texts,
                model=embedding_model,
                api_key=api_key,
                base_url=base_url,
                **_azure_api_kwargs(),
            ),
        )

    async def llm_model_func(prompt, system_prompt=None, history_messages=None, **kwargs):
        kwargs = dict(kwargs)
        kwargs.setdefault("max_tokens", max_tokens)
        kwargs.setdefault("temperature", temperature)
        return await azure_openai_complete_if_cache(
            llm_model,
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages or [],
            api_key=api_key,
            base_url=base_url,
            **_azure_api_kwargs(),
            **kwargs,
        )

    async def vision_model_func(prompt, system_prompt=None, history_messages=None, image_data=None, messages=None, **kwargs):
        kwargs = dict(kwargs)
        kwargs.setdefault("max_tokens", max_tokens)
        kwargs.setdefault("temperature", temperature)
        if messages:
            return await azure_openai_complete_if_cache(
                vision_model,
                None,
                system_prompt=None,
                history_messages=messages,
                api_key=api_key,
                base_url=base_url,
                **_azure_api_kwargs(),
                **kwargs,
            )
        if image_data:
            if isinstance(image_data, dict):
                image_base64 = image_data.get("base64")
                image_mime = image_data.get("mime") or "image/png"
            else:
                image_base64 = image_data
                image_mime = "image/png"
            structured_messages = [
                {"role": "system", "content": system_prompt} if system_prompt else None,
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{image_base64}"}} if image_base64 else None,
                    ],
                },
            ]
            structured_messages = [m for m in structured_messages if m]
            return await azure_openai_complete_if_cache(
                vision_model,
                None,
                system_prompt=None,
                history_messages=structured_messages,
                api_key=api_key,
                base_url=base_url,
                **_azure_api_kwargs(),
                **kwargs,
            )
        return await llm_model_func(prompt, system_prompt, history_messages, **kwargs)

    async def rerank_model_func(query: str, documents: List[str], top_n: Optional[int] = None, **_: Any) -> List[Dict[str, float]]:
        texts = [query] + documents
        embeddings = await embedding_func(texts)  # type: ignore[misc]
        query_vec = np.array(embeddings[0])
        doc_vecs = [np.array(e) for e in embeddings[1:]]
        scores = [float(np.dot(doc, query_vec)) for doc in doc_vecs]
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        if top_n is not None:
            order = order[:top_n]
        return [{"index": i, "relevance_score": scores[i]} for i in order]

    rag_config = RAGAnythingConfig(
        working_dir=args.working_dir,
        parser=os.getenv("PARSER", "mineru"),
        parse_method=os.getenv("PARSE_METHOD", "auto"),
        enable_image_processing=_env_flag("ENABLE_IMAGE_PROCESSING", "true"),
        enable_table_processing=_env_flag("ENABLE_TABLE_PROCESSING", "true"),
        enable_equation_processing=_env_flag("ENABLE_EQUATION_PROCESSING", "true"),
        enable_micro_planner=_env_flag("ENABLE_MICRO_PLANNER", "true"),
    )
    rag = RAGAnything(
        llm_model_func=llm_model_func,
        vision_model_func=vision_model_func,
        embedding_func=embedding_func,
        config=rag_config,
        lightrag_kwargs={"rerank_model_func": rerank_model_func},
    )
    if rag.micro_planner:
        rag.micro_planner.evaluator_func = None

    if args.knowledge_dir:
        knowledge_dir = Path(args.knowledge_dir).expanduser()
        rag_output = Path(args.rag_output).expanduser()
        supported_exts = (
            [ext.strip() for ext in args.supported_exts.split(",") if ext.strip()]
            if args.supported_exts
            else _env_list("SUPPORTED_FILE_EXTENSIONS")
        )
        await _ingest_knowledge(
            rag,
            knowledge_dir=knowledge_dir,
            output_dir=rag_output,
            recursive=args.knowledge_recursive or _env_flag("RECURSIVE_FOLDER_PROCESSING", "false"),
            supported_exts=supported_exts,
        )

    if args.image_root:
        image_root = Path(args.image_root).expanduser()
    elif args.data_root:
        candidate = Path(args.data_root).expanduser() / "images"
        image_root = candidate if candidate.exists() else None
    else:
        image_root = None

    metadata_priority: List[str] = []
    metadata_priority.extend(split_qids.get("train", []))
    metadata_priority.extend(split_qids.get("val", []))
    metadata_priority.extend(qids)
    metadata_qids = list(dict.fromkeys(metadata_priority))
    await _ingest_problem_metadata(rag, problems, metadata_qids, image_root)

    shot_context = _build_shot_section(problems, shot_qids, args.use_caption)

    output_root = Path(args.output_root).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)
    result_file = output_root / f"{args.label}_{args.test_split}.json"
    trace_file = output_root / f"{args.label}_{args.test_split}_trace.json"
    summary_file = output_root / f"{args.label}_{args.test_split}_summary.json"

    results: Dict[str, str] = {}
    traces: Dict[str, Any] = {}
    correct = 0
    total = 0
    failed: List[str] = []
    subject_totals: Counter[str] = Counter()
    subject_correct: Counter[str] = Counter()

    iterator: Iterable[str]
    if args.debug:
        iterator = qids
    else:
        iterator = tqdm(qids, desc="ScienceQA", unit="q")

    delay = max(0.0, args.rate_limit_delay)
    base_wait = delay if delay > 0 else 1.0
    backoff = max(1.0, args.rate_limit_backoff)
    retries = max(0, args.rate_limit_retries)

    request_timeout = _env_int("SCIENCEQA_REQUEST_TIMEOUT", _env_int("TIMEOUT", 240))

    async def call_with_retry(coro_factory, description: str):
        attempt = 0
        while True:
            try:
                logger.info(f"{description} attempt {attempt + 1} (timeout={request_timeout}s)")
                result = await asyncio.wait_for(coro_factory(), timeout=request_timeout)
                if delay > 0:
                    await asyncio.sleep(delay)
                return result
            except asyncio.TimeoutError:
                logger.error(f"{description} timed out after {request_timeout}s (attempt {attempt + 1})")
                if attempt >= retries:
                    raise
                wait = base_wait * (backoff ** attempt)
                tqdm.write(f"{description} timeout; sleeping {wait:.1f}s before retry")
                await asyncio.sleep(wait)
                attempt += 1
            except Exception as exc:
                if not _is_rate_limit_error(exc) or attempt >= retries:
                    raise
                wait = base_wait * (backoff ** attempt)
                retry_after = _extract_retry_after(exc)
                if retry_after:
                    wait = max(wait, retry_after)
                msg = f"{description} hit rate limit (attempt {attempt + 1}/{retries + 1}); retrying in {wait:.1f}s"
                tqdm.write(msg)
                logger.warning(msg)
                await asyncio.sleep(wait)
                attempt += 1

    for idx, qid in enumerate(iterator, start=1):
        logger.info(f"[ScienceQA] Start question {idx}/{len(qids)} (qid={qid})")
        problem = problems[qid]
        question_text = problem.get("question", "")

        planner_report: Optional[Dict[str, Any]] = None
        if rag and rag.micro_planner:
            try:
                normalized_query, planner_meta = rag.micro_planner.normalize(question_text)
                intent_result = rag.micro_planner.detect_intent(normalized_query, planner_meta)
                plan = rag.micro_planner.compile_strategy(intent_result.intent, intent_result.tags)
                budgets = {
                    "time_ms": _env_int("MICRO_PLANNER_TIME_MS", 1000),
                    "memory_gb": _env_float("MICRO_PLANNER_MEMORY_GB", 2.0),
                }
                plan = rag.micro_planner.apply_policies(plan, budgets)
                planner_report = plan.to_dict(question_text, normalized_query, intent_result.intent, intent_result.tags)
                logger.info(
                    "[Planner] qid=%s intent=%s tags=%s plan=%s",
                    qid,
                    intent_result.intent,
                    intent_result.tags,
                    json.dumps(planner_report.get("plan", {}), ensure_ascii=False),
                )
            except Exception as exc:
                logger.warning(f"[Planner] Failed to build plan for qid={qid}: {exc}")

        context: Optional[str] = None
        if rag:
            context = await _retrieve_context(
                rag,
                question_text,
                args.mode,
                args.top_k,
            )
            logger.info(
                f"[ScienceQA] Retrieved context for qid={qid}: "
                f"{'none' if context is None else f'{len(context.split())} words'}"
            )
            if context:
                preview = context.strip()
                if len(preview) > 200:
                    preview = preview[:200] + "..."
                logger.info(f"[Query] qid={qid} context preview: {preview}")

        clean_context = context
        if clean_context and clean_context.strip().lower().startswith("sorry"):
            logger.info(f"[Query] qid={qid} context indicates no retrieval; omitting from prompt")
            clean_context = None

        prompt, valid_letters = _build_prompt(problem, clean_context, shot_context, args.use_caption)
        image_path = _resolve_image_path(problem, image_root, qid)
        use_image = bool(image_path and not args.force_text)
        logger.info(
            f"[ScienceQA] Prepared prompt for qid={qid}; "
            f"choices={len(valid_letters)}, use_image={use_image}"
        )

        image_mime: Optional[str] = None
        effective_use_image = use_image

        if args.dry_run:
            response_text = ""
            predicted = valid_letters[0] if valid_letters else ""
        else:
            response_text = ""
            effective_use_image = use_image
            if use_image and image_path:
                encoded_image = _encode_image_to_base64(image_path)
                if encoded_image:
                    image_base64, image_mime = encoded_image
                    image_payload = {"base64": image_base64, "mime": image_mime}
                    logger.info(f"[ScienceQA] Using image for qid={qid}: {image_path} ({image_mime})")
                    try:
                        start_time = time.perf_counter()

                        async def call_vision():
                            return await vision_model_func(
                                prompt,
                                system_prompt=DEFAULT_SYSTEM_PROMPT,
                                image_data=image_payload,
                            )

                        response_text = await call_with_retry(call_vision, f"[{qid}] vision completion")
                        elapsed = time.perf_counter() - start_time
                        logger.info(f"[ScienceQA] Vision completion for qid={qid} succeeded in {elapsed:.2f}s")
                    except Exception as exc:
                        logger.error(f"[{qid}] Vision call failed: {exc}")
                        effective_use_image = False
                else:
                    logger.warning(f"[ScienceQA] Failed to encode image for qid={qid}: {image_path}")
                    effective_use_image = False

            if not response_text:
                try:
                    start_time = time.perf_counter()

                    async def call_text():
                        return await llm_model_func(
                            prompt,
                            system_prompt=DEFAULT_SYSTEM_PROMPT,
                        )

                    response_text = await call_with_retry(call_text, f"[{qid}] text completion")
                    elapsed = time.perf_counter() - start_time
                    logger.info(f"[ScienceQA] Text completion for qid={qid} succeeded in {elapsed:.2f}s")
                except Exception as exc:
                    logger.error(f"[{qid}] LLM call failed: {exc}")
            else:
                pass
            predicted = _normalize_letter(response_text, valid_letters) or ""

        reflection_report: Optional[Dict[str, Any]] = None
        if rag and rag.micro_planner:
            try:
                reflection_report = rag.micro_planner.evaluate(
                    question_text,
                    response_text,
                    {"context": context or ""},
                )
                logger.info(
                    "[Reflection] qid=%s score=%s reason=%s",
                    qid,
                    reflection_report.get("score"),
                    reflection_report.get("degrade_reason"),
                )
            except Exception as exc:
                logger.warning(f"[Reflection] Evaluation failed for qid={qid}: {exc}")

        answer = problem.get("answer")
        if isinstance(answer, int) and 0 <= answer < len(valid_letters):
            gt_letter = valid_letters[answer]
        elif isinstance(answer, str):
            gt_letter = answer.strip().upper()
        else:
            gt_letter = ""

        is_correct = bool(predicted and gt_letter and predicted == gt_letter)

        results[qid] = predicted
        traces[qid] = {
            "prompt": prompt,
            "context": context,
            "response": response_text,
            "valid_letters": valid_letters,
            "shot_qids": shot_qids,
            "image_path": str(image_path) if effective_use_image and image_path else None,
            "image_mime": image_mime if effective_use_image and image_mime else None,
            "planner": planner_report,
            "reflection": reflection_report,
            "ground_truth": gt_letter,
            "is_correct": is_correct,
        }
        logger.info(
            f"[Result] qid={qid} predicted={predicted or 'N/A'} "
            f"ground_truth={gt_letter or 'N/A'} correct={is_correct}"
        )

        if gt_letter:
            total += 1
            if is_correct:
                correct += 1
            else:
                failed.append(qid)
            subject_name = str(problem.get("subject", "unknown") or "unknown")
            subject_totals[subject_name] += 1
            if is_correct:
                subject_correct[subject_name] += 1

        if args.save_every > 0 and idx % args.save_every == 0:
            with result_file.open("w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            with trace_file.open("w", encoding="utf-8") as f:
                json.dump(traces, f, indent=2, ensure_ascii=False)
            print(f"Results saved to {result_file} after {idx} examples.")

        if args.debug and idx >= 10:
            break

    with result_file.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    with trace_file.open("w", encoding="utf-8") as f:
        json.dump(traces, f, indent=2, ensure_ascii=False)

    accuracy = (correct / total) if total else 0.0
    subject_accuracy = {
        subject: {
            "correct": subject_correct.get(subject, 0),
            "total": count,
            "accuracy": subject_correct.get(subject, 0) / count if count else 0.0,
        }
        for subject, count in subject_totals.items()
    }
    summary = {
        "evaluated": total,
        "correct": correct,
        "accuracy": accuracy,
        "subject_accuracy": subject_accuracy,
        "failed": failed,
    }
    with summary_file.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"Results saved to {result_file}")
    print(f"Traces saved to {trace_file}")
    print(f"Summary saved to {summary_file}")
    if total:
        print(f"Number of correct answers: {correct}/{total}")
        print(f"Accuracy: {accuracy:.4f}")
        if subject_accuracy:
            print("Per-subject accuracy:")
            for subject, stats in sorted(subject_accuracy.items()):
                print(
                    f"  {subject}: {stats['accuracy']:.4f} "
                    f"({stats['correct']} / {stats['total']})"
                )
    if failed:
        print(f"Failed question ids: {failed[:20]}{'...' if len(failed) > 20 else ''}")


def main() -> None:
    configure_logging()
    args = parse_args()

    print("====Input Arguments====")
    safe_args = dict(vars(args))
    if safe_args.get("openai_key"):
        safe_args["openai_key"] = "***"
    print(json.dumps(safe_args, indent=2, sort_keys=False, default=str))

    random.seed(args.seed)
    problems, qids, shot_qids, split_qids = load_data(args)

    asyncio.run(run_scienceqa(args, problems, qids, shot_qids, split_qids))


if __name__ == "__main__":
    main()

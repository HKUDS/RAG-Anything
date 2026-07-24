from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv


logger = logging.getLogger('rag_server.runtime_settings')

RUNTIME_SETTINGS_FILE_ENV = 'RUNTIME_SETTINGS_FILE'
RUNTIME_SETTINGS_FILE_DEFAULT = 'config/runtime_settings.json'

_BOOTSTRAP_DONE = False
_BOOT_DEFAULTS = None

_FIELD_SPECS = (
    (('parser',), 'PARSER', 'str', 'docling'),
    (('entity_types',), 'ENTITY_TYPES', 'raw', ''),
    (('entity_extraction_min_degree',), 'ENTITY_EXTRACTION_MIN_DEGREE', 'int', 0),
    (('llm_model',), 'LLM_MODEL', 'str', 'qwen-plus'),
    (('chunk_size',), 'CHUNK_SIZE', 'int', 800),
    (('chunking_strategy',), 'CHUNKING_STRATEGY', 'str', 'recursive'),
    (('max_async',), 'MAX_ASYNC', 'int', 4),
    (('llm_timeout',), 'LLM_TIMEOUT', 'int', 180),
    (('enable_image',), 'ENABLE_IMAGE_PROCESSING', 'bool', True),
    (('enable_table',), 'ENABLE_TABLE_PROCESSING', 'bool', True),
    (('enable_equation',), 'ENABLE_EQUATION_PROCESSING', 'bool', True),
    (('enable_video',), 'ENABLE_VIDEO_PROCESSING', 'bool', False),
    (('rrf', 'rrf_k'), 'RRF_K', 'int', 60),
    (('rrf', 'bm25_top_k'), 'BM25_TOP_K', 'int', 50),
    (('rrf', 'vector_top_k'), 'VECTOR_TOP_K', 'int', 100),
    (('rrf', 'graph_top_k'), 'GRAPH_TOP_K', 'int', 30),
    (('rrf', 'graph_depth'), 'GRAPH_DEPTH', 'int', 2),
    (('rrf', 'bm25_k1'), 'BM25_K1', 'float', 1.5),
    (('rrf', 'bm25_b'), 'BM25_B', 'float', 0.75),
    (('rrf', 'bm25_tokenizer'), 'BM25_TOKENIZER', 'str', 'jieba'),
    (('rrf', 'rrf_channel_timeout'), 'RRF_CHANNEL_TIMEOUT', 'float', 0.15),
    (('rrf', 'enabled_channels'), 'RRF_ENABLED_CHANNELS', 'str', 'bm25,vector,graph'),
)


def _settings_path() -> Path:
    return Path(os.getenv(RUNTIME_SETTINGS_FILE_ENV, RUNTIME_SETTINGS_FILE_DEFAULT))


def _coerce(value, kind, default):
    if value is None:
        return default
    if kind == 'bool':
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() == 'true'
    if kind == 'int':
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    if kind == 'float':
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    text = str(value).strip()
    if kind == 'raw':
        return text
    return text or default


def _stringify(value):
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _read_nested(source, path):
    cursor = source
    for part in path:
        if not isinstance(cursor, dict) or part not in cursor:
            return False, None
        cursor = cursor[part]
    return True, cursor


def _set_nested(target, path, value):
    cursor = target
    for part in path[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[path[-1]] = value


def snapshot_current_settings():
    snapshot = {}
    for path, env_key, kind, default in _FIELD_SPECS:
        _set_nested(snapshot, path, _coerce(os.getenv(env_key), kind, default))
    return snapshot


def _coerce_partial_snapshot(raw_snapshot):
    normalized = {}
    for path, _env_key, kind, default in _FIELD_SPECS:
        exists, raw_value = _read_nested(raw_snapshot, path)
        if exists:
            _set_nested(normalized, path, _coerce(raw_value, kind, default))
    return normalized


def _read_persisted_overrides():
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        raw_data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, json.JSONDecodeError):
        logger.warning('Failed to read runtime settings overrides from %s', path, exc_info=True)
        return {}
    if not isinstance(raw_data, dict):
        logger.warning('Ignoring runtime settings overrides from %s because the payload is not a JSON object', path)
        return {}
    return _coerce_partial_snapshot(raw_data)


def apply_persisted_settings():
    overrides = _read_persisted_overrides()
    for path, env_key, kind, default in _FIELD_SPECS:
        exists, raw_value = _read_nested(overrides, path)
        if exists:
            os.environ[env_key] = _stringify(_coerce(raw_value, kind, default))
    return overrides


def _diff_snapshots(base, current):
    diff = {}
    for key, value in current.items():
        base_value = base.get(key)
        if isinstance(value, dict):
            nested = _diff_snapshots(base_value if isinstance(base_value, dict) else {}, value)
            if nested:
                diff[key] = nested
        elif value != base_value:
            diff[key] = value
    return diff


def _write_persisted_overrides(overrides):
    path = _settings_path()
    if not overrides:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f'{path.name}.tmp')
    temp_path.write_text(
        json.dumps(overrides, ensure_ascii=True, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    os.replace(temp_path, path)


def bootstrap_runtime_settings():
    global _BOOTSTRAP_DONE, _BOOT_DEFAULTS
    if _BOOTSTRAP_DONE:
        return
    load_dotenv(dotenv_path='.env', override=False)
    if _BOOT_DEFAULTS is None:
        _BOOT_DEFAULTS = snapshot_current_settings()
    apply_persisted_settings()
    _BOOTSTRAP_DONE = True


def get_boot_settings_snapshot():
    bootstrap_runtime_settings()
    return copy.deepcopy(_BOOT_DEFAULTS or snapshot_current_settings())


def sync_persisted_settings_from_env():
    bootstrap_runtime_settings()
    current = snapshot_current_settings()
    base = _BOOT_DEFAULTS or current
    overrides = _diff_snapshots(base, current)
    _write_persisted_overrides(overrides)
    return overrides


def read_persisted_settings():
    return _read_persisted_overrides()

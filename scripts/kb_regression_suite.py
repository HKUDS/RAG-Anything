from __future__ import annotations

import argparse
import codecs
import json
import mimetypes
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:8001/api"
DEFAULT_OUTPUT_DIR = Path("output") / "kb-regression"
DEFAULT_DOCX = Path(
    "D:\\Users\\98014\\Desktop\\"
    "\u4eba\u5de5\u667a\u80fd222+2022010940231\\"
    "\u4e0a\u62a5\u5b66\u6821\u5b58\u6863\\1.Word\\3.\u5f00\u9898\u62a5\u544a.docx"
)
DEFAULT_PDF = Path(
    "D:\\Users\\98014\\Desktop\\"
    "\u4eba\u5de5\u667a\u80fd222+2022010940231\\"
    "\u4e0a\u62a5\u5b66\u6821\u5b58\u6863\\2.PDF\\3.\u5f00\u9898\u62a5\u544a.pdf"
)
DEFAULT_VIDEO = Path(
    "D:\\Users\\98014\\Downloads\\8\u3001\u8f66\u8f86\u5185\u90e8\u68c0\u67e5 (1).mp4"
)

STRATEGIES = ["fixed_size", "recursive", "sentence", "structure", "semantic", "agentic"]
FILE_TYPES = ["docx", "pdf", "video"]
SMOKE_MATRIX = [
    ("fixed_size", "docx"),
    ("structure", "pdf"),
    ("fixed_size", "video"),
]
TASK_DONE = {"completed", "failed", "deleted"}
DOC_SUCCESS = {"processed", "completed"}
DOC_DONE = DOC_SUCCESS | {"failed"}
NAME_RE = re.compile(r"^test(\d{2,})$", re.I)
RBAC_REQUIRED_ROLES = ("super_admin", "dept_admin", "teacher", "assistant", "student")
DOCUMENT_SETTLE_CAP_SECONDS = 45.0
DELETE_RESPONSE_BUDGET_SECONDS = 30.0
AUTH_REFRESH_SECONDS = 55 * 60
CHUNK_REQUIRED_FIELDS = {
    "chunk_id",
    "content",
    "tokens",
    "chunk_order_index",
    "file_path",
    "is_multimodal",
    "original_type",
    "modal_entity_name",
    "page_idx",
    "media_path",
    "media_url",
}
LOG_KEYWORDS = (
    "error",
    "exception",
    "traceback",
    "failed",
    "runtimeerror",
    "permissionerror",
    "apiconnectionerror",
    "openai",
    "connection error",
    "ffmpeg",
    "docling",
    "additional.dat",
    "refused",
    "denied",
    "拒绝访问",
)
INLINE_MEDIA_HINTS = (
    "[图片",
    "[图像",
    "[image",
    "[表格",
    "[table",
    "[公式",
    "[equation",
    "[视频",
    "[video",
    "image content analysis:",
    "table analysis:",
    "mathematical equation analysis:",
    "video content analysis:",
    "image_",
    "table_",
    "equation_",
    "video_",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".mp4",
    "video_path",
    "equation_img_path",
)


class SuiteError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm_url(url: str) -> str:
    clean = (url or DEFAULT_BASE_URL).strip().rstrip("/")
    return clean if clean.endswith("/api") else f"{clean}/api"


def strip_hash(name: str) -> str:
    return re.sub(r"^[0-9a-f]{8}_", "", Path(name or "").name)


def matrix(profile: str, strategies: list[str], file_types: list[str]) -> list[tuple[str, str]]:
    kinds = file_types or FILE_TYPES
    if strategies:
        return [(strategy, kind) for strategy in strategies for kind in kinds]
    if profile == "smoke":
        return [item for item in SMOKE_MATRIX if item[1] in kinds]
    return [(strategy, kind) for strategy in STRATEGIES for kind in kinds]


def build_samples(docx: Path, pdf: Path, video: Path) -> dict[str, dict[str, Any]]:
    return {
        "docx": {
            "path": docx,
            "file_type": "docx",
            "require_multimodal": False,
            "toggles": {
                "enable_image": True,
                "enable_table": True,
                "enable_equation": True,
                "enable_video": False,
            },
        },
        "pdf": {
            "path": pdf,
            "file_type": "pdf",
            "require_multimodal": False,
            "toggles": {
                "enable_image": True,
                "enable_table": True,
                "enable_equation": True,
                "enable_video": False,
            },
        },
        "video": {
            "path": video,
            "file_type": "video",
            "require_multimodal": True,
            "toggles": {
                "enable_image": False,
                "enable_table": False,
                "enable_equation": False,
                "enable_video": True,
            },
        },
    }


def preflight(samples: dict[str, dict[str, Any]]) -> None:
    missing = [str(item["path"]) for item in samples.values() if not Path(item["path"]).exists()]
    if missing:
        raise SuiteError("Missing sample files: " + "; ".join(missing))


def isolated_upload_copy(source: Path) -> Path:
    """Create a per-attempt upload copy so long-running workers do not lock later scenarios."""
    temp_dir = Path(tempfile.gettempdir()) / "kb-regression-suite"
    temp_dir.mkdir(parents=True, exist_ok=True)
    copy_path = temp_dir / f"{uuid4().hex[:8]}_{source.name}"
    shutil.copy2(source, copy_path)
    return copy_path


def cleanup_temp_path(path: Path | None) -> None:
    if not path:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def stringify_details(details: Any) -> str:
    if details is None:
        return ""
    if isinstance(details, str):
        return details
    try:
        return json.dumps(details, ensure_ascii=False, default=str)
    except TypeError:
        return str(details)


def classify_issue(details: Any) -> dict[str, str] | None:
    text = stringify_details(details).lower()
    if not text:
        return None

    def issue(kind: str, code: str, summary: str) -> dict[str, str]:
        return {"kind": kind, "code": code, "summary": summary}

    if ("ffmpeg" in text and ("winerror 5" in text or "permissionerror" in text or "access is denied" in text or "拒绝访问" in text)):
        return issue("environment", "ffmpeg_permission_denied", "Video processor could not invoke ffmpeg due to local permission denial.")
    if ("additional.dat" in text and "docling" in text) or ("docling_parse" in text and "filename does not exists" in text):
        return issue("environment", "docling_resource_missing", "PDF parsing resources are missing from the Docling runtime.")
    if "apiconnectionerror" in text or "openai api connection error" in text or ("retryerror" in text and "connection error" in text):
        return issue("environment", "llm_connectivity_blocked", "External LLM/VLM connectivity failed during document processing.")
    if "winerror 10061" in text or "connection refused" in text or "actively refused" in text or "all connection attempts failed" in text:
        return issue("environment", "api_server_unavailable", "The API server became unreachable during the suite run.")
    if "timeout" in text or "timed out" in text:
        return issue("environment", "timeout", "A dependent process timed out before the suite could complete.")
    if "winerror 5" in text or "permissionerror" in text or "access is denied" in text or "拒绝访问" in text:
        return issue("environment", "local_permission_denied", "A local runtime dependency hit an access-denied error.")
    return None


def make_check(
    name: str,
    passed: bool,
    details: Any,
    severity: str = "error",
    classification: dict[str, str] | None = None,
) -> dict[str, Any]:
    item = {
        "name": name,
        "passed": bool(passed),
        "severity": severity,
        "details": details,
    }
    if not passed:
        issue = classification or classify_issue(details)
        if issue:
            item["classification"] = issue
    return item


def add_check(
    result: dict[str, Any],
    name: str,
    passed: bool,
    details: Any,
    severity: str = "error",
    classification: dict[str, str] | None = None,
) -> None:
    result.setdefault("checks", []).append(make_check(name, passed, details, severity, classification))


def summarize_failed_checks(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for item in checks:
        if item.get("passed"):
            continue
        summary.append(
            {
                "name": item.get("name"),
                "severity": item.get("severity"),
                "classification": item.get("classification"),
            }
        )
    return summary


def finish(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("skipped"):
        result["passed"] = True
        result["status"] = "skipped"
        return result
    checks = result.get("checks", [])
    error_failures = [item for item in checks if (not item.get("passed")) and item.get("severity") == "error"]
    if not error_failures:
        result["passed"] = True
        result["status"] = "passed"
        result["failure_summary"] = summarize_failed_checks(checks)
        return result

    classifications = [item.get("classification", {}) for item in error_failures]
    has_environment = any(item.get("kind") == "environment" for item in classifications if item)
    has_non_environment = any(item and item.get("kind") != "environment" for item in classifications)
    blocked = has_environment and not has_non_environment
    result["passed"] = False
    result["status"] = "blocked" if blocked else "failed"
    result["failure_summary"] = summarize_failed_checks(checks)
    return result


def group_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "passed": sum(1 for item in results if item.get("status") == "passed"),
        "failed": sum(1 for item in results if item.get("status") == "failed"),
        "blocked": sum(1 for item in results if item.get("status") == "blocked"),
        "skipped": sum(1 for item in results if item.get("status") == "skipped"),
        "warnings": sum(
            1
            for item in results
            for check in item.get("checks", [])
            if check.get("severity") == "warning" and not check.get("passed")
        ),
        "total": len(results),
    }


class NameAllocator:
    def __init__(self, used: set[str]) -> None:
        self.used = {item.lower() for item in used}

    def next(self) -> str:
        for number in range(1, 1000):
            name = f"test{number:02d}"
            if name.lower() not in self.used:
                self.used.add(name.lower())
                return name
        raise SuiteError("No free testNN name remained in the 01-999 range")


def used_test_names(kb_data: dict[str, Any], agent_data: dict[str, Any]) -> set[str]:
    used: set[str] = set()
    for kb in kb_data.get("knowledge_bases", []):
        name = str(kb.get("name", ""))
        if NAME_RE.match(name):
            used.add(name)
    for agent in agent_data.get("agents", []):
        name = str(agent.get("name", ""))
        if NAME_RE.match(name):
            used.add(name)
    return used


def task_snapshot(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task.get("task_id"),
        "status": task.get("status"),
        "progress": task.get("progress"),
        "phase": task.get("phase"),
        "updated_at": task.get("updated_at"),
        "error_message": task.get("error_message"),
    }


def doc_snapshot(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc.get("id"),
        "full_id": doc.get("full_id"),
        "file": doc.get("file"),
        "status": doc.get("status"),
        "chunks": doc.get("chunks"),
        "phase": doc.get("phase"),
        "updated": doc.get("updated"),
    }


def matches_filename(candidate: str, filename: str) -> bool:
    return strip_hash(candidate) == Path(filename).name


def doc_id_of(doc: dict[str, Any]) -> str:
    return str(doc.get("full_id") or doc.get("id") or "")


class ApiClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.client = httpx.Client(base_url=norm_url(base_url), timeout=timeout, follow_redirects=True)
        self._username = ""
        self._password = ""
        self._login_monotonic = 0.0

    def close(self) -> None:
        self.client.close()

    def _decode_response(self, response: httpx.Response, raw: bool) -> Any:
        if raw:
            return response.content
        content_type = response.headers.get("content-type", "")
        return response.json() if "application/json" in content_type else response.text

    def _store_token(self, data: dict[str, Any]) -> None:
        self.client.headers["Authorization"] = "Bearer " + str(data.get("access_token", ""))
        self._login_monotonic = time.monotonic()

    def _perform_login(self, username: str, password: str) -> dict[str, Any]:
        response = self.client.request("POST", "/auth/login", json={"username": username, "password": password})
        data = self._decode_response(response, raw=False)
        if response.status_code != 200:
            raise SuiteError(f"POST /auth/login -> {response.status_code}: {data}")
        self._store_token(data)
        return data

    def ensure_authenticated(self) -> None:
        if not self._username or not self._password:
            return
        if not self._login_monotonic or time.monotonic() - self._login_monotonic >= AUTH_REFRESH_SECONDS:
            self._perform_login(self._username, self._password)

    def req(
        self,
        method: str,
        path: str,
        expected: tuple[int, ...] = (200,),
        raw: bool = False,
        **kwargs: Any,
    ) -> tuple[httpx.Response, Any]:
        if path != "/auth/login":
            self.ensure_authenticated()
        response = self.client.request(method, path, **kwargs)
        if response.status_code == 401 and path != "/auth/login" and self._username and self._password and "files" not in kwargs:
            self._perform_login(self._username, self._password)
            response = self.client.request(method, path, **kwargs)
        data = self._decode_response(response, raw)
        if expected and response.status_code not in expected:
            raise SuiteError(f"{method} {path} -> {response.status_code}: {data}")
        return response, data

    def login(self, username: str, password: str) -> dict[str, Any]:
        self._username = username
        self._password = password
        return self._perform_login(username, password)

    def auth_me(self) -> dict[str, Any]:
        _, data = self.req("GET", "/auth/me")
        return data

    def kbs(self) -> dict[str, Any]:
        _, data = self.req("GET", "/kb/list")
        return data

    def agents(self) -> dict[str, Any]:
        _, data = self.req("GET", "/agents")
        return data

    def create_kb(self, name: str) -> dict[str, Any]:
        _, data = self.req("POST", "/kb/create", params={"kb_name": name, "label": name, "domain": "regression"})
        return data

    def switch_kb(self, name: str) -> dict[str, Any]:
        _, data = self.req("PUT", "/kb/switch", params={"name": name})
        return data

    def delete_kb(self, name: str, expected: tuple[int, ...] = (200,)) -> dict[str, Any]:
        _, data = self.req("DELETE", f"/kb/{name}", expected=expected)
        return data

    def create_agent(self, name: str) -> dict[str, Any]:
        payload = {"name": name, "description": f"Regression agent for {name}", "kb_name": name}
        _, data = self.req("POST", "/agents", json=payload)
        return data

    def delete_agent(self, agent_id: str, expected: tuple[int, ...] = (200,)) -> dict[str, Any]:
        _, data = self.req("DELETE", f"/agents/{agent_id}", expected=expected)
        return data

    def roles(self) -> dict[str, Any]:
        _, data = self.req("GET", "/admin/roles")
        return data

    def create_user(self, username: str, email: str, password: str, role_id: int) -> dict[str, Any]:
        payload = {"username": username, "email": email, "password": password, "role_id": role_id}
        _, data = self.req("POST", "/admin/users", expected=(201,), json=payload)
        return data

    def delete_user(self, user_id: int, expected: tuple[int, ...] = (200,)) -> dict[str, Any]:
        _, data = self.req("DELETE", f"/admin/users/{user_id}", expected=expected)
        return data

    def upload_file(self, kb_name: str, file_path: Path, strategy: str, toggles: dict[str, Any], expected: tuple[int, ...] = (200,)) -> dict[str, Any]:
        params = {
            "kb": kb_name,
            "chunking_strategy": strategy,
            "enable_image": str(bool(toggles.get("enable_image"))).lower(),
            "enable_table": str(bool(toggles.get("enable_table"))).lower(),
            "enable_equation": str(bool(toggles.get("enable_equation"))).lower(),
            "enable_video": str(bool(toggles.get("enable_video"))).lower(),
        }
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        with file_path.open("rb") as handle:
            _, data = self.req(
                "POST",
                "/upload",
                expected=expected,
                params=params,
                files={"file": (file_path.name, handle, mime_type)},
            )
        return data

    def tasks(self, kb_name: str) -> dict[str, Any]:
        _, data = self.req("GET", "/upload/tasks", params={"kb": kb_name})
        return data

    def delete_task(self, kb_name: str, task_id: str, expected: tuple[int, ...] = (200,)) -> dict[str, Any]:
        _, data = self.req("DELETE", f"/upload/tasks/{task_id}", expected=expected, params={"kb": kb_name})
        return data

    def documents(self, kb_name: str) -> dict[str, Any]:
        _, data = self.req("GET", "/knowledge/documents", params={"kb": kb_name})
        return data

    def chunks(self, kb_name: str, doc_id: str) -> dict[str, Any]:
        _, data = self.req("GET", f"/knowledge/documents/{doc_id}/chunks", params={"kb": kb_name})
        return data

    def stats(self, kb_name: str) -> dict[str, Any]:
        _, data = self.req("GET", "/knowledge/stats", params={"kb": kb_name})
        return data

    def batch_stats(self, kb_names: list[str]) -> dict[str, Any]:
        _, data = self.req("POST", "/knowledge/stats/batch", json={"kb_names": kb_names})
        return data

    def entities(self, kb_name: str, limit: int = 200) -> dict[str, Any]:
        _, data = self.req("GET", "/knowledge/entities", params={"kb": kb_name, "limit": limit})
        return data

    def graph(self, kb_name: str) -> dict[str, Any]:
        _, data = self.req("GET", "/knowledge/graph", params={"kb": kb_name})
        return data

    def graph_node(self, kb_name: str, entity_name: str) -> dict[str, Any]:
        encoded = quote(entity_name, safe="")
        _, data = self.req("GET", f"/knowledge/graph/nodes/{encoded}", params={"kb": kb_name})
        return data

    def download_document(self, kb_name: str, doc_id: str) -> tuple[httpx.Response, bytes]:
        response, data = self.req("GET", f"/knowledge/documents/{doc_id}/download", raw=True, params={"kb": kb_name})
        return response, data

    def delete_document(self, kb_name: str, doc_id: str, expected: tuple[int, ...] = (200,)) -> dict[str, Any]:
        _, data = self.req("DELETE", f"/knowledge/documents/{doc_id}", expected=expected, params={"kb": kb_name})
        return data

    def retry_document(self, kb_name: str, doc_id: str, expected: tuple[int, ...] = (200,)) -> dict[str, Any]:
        _, data = self.req("POST", f"/knowledge/documents/{doc_id}/retry", expected=expected, params={"kb": kb_name})
        return data

    def vision_embedding_health(self) -> dict[str, Any]:
        _, data = self.req("GET", "/health/vision-embedding")
        return data

    def reprocess_multimodal(self, kb_name: str, expected: tuple[int, ...] = (200,)) -> dict[str, Any]:
        _, data = self.req("POST", f"/kb/{kb_name}/reprocess-multimodal", expected=expected)
        return data


def wait_for_task(api: ApiClient, kb_name: str, task_id: str, timeout: float, poll_interval: float) -> tuple[dict[str, Any], list[dict[str, Any]], float]:
    start = time.monotonic()
    timeline: list[dict[str, Any]] = []
    last: dict[str, Any] | None = None
    while time.monotonic() - start <= timeout:
        tasks = api.tasks(kb_name).get("tasks", [])
        task = next((item for item in tasks if item.get("task_id") == task_id), None)
        if task:
            snapshot = task_snapshot(task)
            if snapshot != last:
                timeline.append(snapshot)
                last = snapshot
            if task.get("status") in TASK_DONE:
                return task, timeline, round(time.monotonic() - start, 2)
        time.sleep(poll_interval)
    raise SuiteError(f"Timeout while waiting for task {task_id} in KB {kb_name}")


def wait_for_document(
    api: ApiClient,
    kb_name: str,
    filename: str,
    timeout: float,
    poll_interval: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], float]:
    start = time.monotonic()
    timeline: list[dict[str, Any]] = []
    last: dict[str, Any] | None = None
    while time.monotonic() - start <= timeout:
        docs = api.documents(kb_name).get("documents", [])
        for doc in docs:
            if matches_filename(str(doc.get("file", "")), filename):
                snapshot = doc_snapshot(doc)
                if snapshot != last:
                    timeline.append(snapshot)
                    last = snapshot
                if doc.get("status") in DOC_DONE:
                    return doc, timeline, round(time.monotonic() - start, 2)
        time.sleep(poll_interval)
    raise SuiteError(f"Timeout while waiting for document {filename} in KB {kb_name}")


def wait_for_document_or_placeholder(
    api: ApiClient,
    kb_name: str,
    filename: str,
    timeout: float,
    poll_interval: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], float, str]:
    start = time.monotonic()
    last_seen_doc: dict[str, Any] | None = None
    last_timeline: list[dict[str, Any]] = []
    try:
        doc, timeline, elapsed = wait_for_document(api, kb_name, filename, timeout, poll_interval)
        return doc, timeline, elapsed, ""
    except Exception as exc:
        docs = api.documents(kb_name).get("documents", [])
        for doc in docs:
            if matches_filename(str(doc.get("file", "")), filename):
                last_seen_doc = doc
                last_timeline = [doc_snapshot(doc)]
                break
        return (
            {
                "id": str((last_seen_doc or {}).get("id") or ""),
                "full_id": str((last_seen_doc or {}).get("full_id") or ""),
                "file": str((last_seen_doc or {}).get("file") or filename),
                "status": str((last_seen_doc or {}).get("status") or "missing_after_task"),
                "chunks": int((last_seen_doc or {}).get("chunks") or 0),
                "phase": str((last_seen_doc or {}).get("phase") or ""),
                "updated": str((last_seen_doc or {}).get("updated") or ""),
                "error": str(exc),
            },
            last_timeline,
            round(time.monotonic() - start, 2),
            str(exc),
        )


def wait_for_absence(api: ApiClient, kb_name: str, filename: str, timeout: float, poll_interval: float) -> bool:
    start = time.monotonic()
    while time.monotonic() - start <= timeout:
        docs = api.documents(kb_name).get("documents", [])
        if not any(matches_filename(str(doc.get("file", "")), filename) for doc in docs):
            return True
        time.sleep(poll_interval)
    return False


def log_offset(log_path: Path | None) -> int:
    if not log_path or not log_path.exists():
        return 0
    return log_path.stat().st_size


def read_log_excerpt(log_path: Path | None, start_offset: int, max_bytes: int = 40000) -> str:
    if not log_path or not log_path.exists():
        return ""
    with log_path.open("rb") as handle:
        handle.seek(0, 2)
        end_offset = handle.tell()
        safe_offset = min(max(start_offset, 0), end_offset)
        if end_offset - safe_offset > max_bytes:
            safe_offset = end_offset - max_bytes
        handle.seek(safe_offset)
        payload = handle.read(max_bytes)
    if payload.startswith(codecs.BOM_UTF16_LE) or payload.startswith(codecs.BOM_UTF16_BE):
        return payload.decode("utf-16", errors="replace").strip()
    utf8_text = payload.decode("utf-8", errors="replace")
    if utf8_text.count("\x00") > max(10, len(utf8_text) // 20):
        try:
            return payload.decode("utf-16-le", errors="replace").strip()
        except Exception:
            return utf8_text.replace("\x00", "").strip()
    return utf8_text.strip()


def extract_log_clues(log_excerpt: str, limit: int = 20) -> list[str]:
    if not log_excerpt:
        return []
    lines = [line.strip() for line in log_excerpt.splitlines() if line.strip()]
    hits = [line for line in lines if any(keyword in line.lower() for keyword in LOG_KEYWORDS)]
    chosen = hits[-limit:] if hits else lines[-limit:]
    return chosen


def attach_log_evidence(result: dict[str, Any], log_path: Path | None, start_offset: int) -> dict[str, Any]:
    excerpt = read_log_excerpt(log_path, start_offset)
    if excerpt:
        result["server_log_path"] = str(log_path)
        result["server_log_excerpt"] = excerpt
        result["server_log_clues"] = extract_log_clues(excerpt)
    return result


def evidence_payload(payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    details = dict(payload)
    if result.get("server_log_clues"):
        details["server_log_clues"] = result["server_log_clues"]
    if result.get("server_log_path"):
        details["server_log_path"] = result["server_log_path"]
    return details


def create_tracker() -> dict[str, list[dict[str, Any]]]:
    return {"kbs": [], "agents": [], "users": []}


def track_kb(tracker: dict[str, list[dict[str, Any]]], name: str, purpose: str) -> None:
    tracker["kbs"].append({"name": name, "purpose": purpose, "deleted": False})


def track_agent(tracker: dict[str, list[dict[str, Any]]], agent: dict[str, Any], kb_name: str, purpose: str) -> None:
    tracker["agents"].append(
        {
            "id": agent.get("id"),
            "name": agent.get("name", kb_name),
            "kb_name": kb_name,
            "purpose": purpose,
            "deleted": False,
        }
    )


def track_user(tracker: dict[str, list[dict[str, Any]]], user: dict[str, Any], purpose: str) -> None:
    tracker["users"].append({"id": user.get("id"), "username": user.get("username"), "purpose": purpose, "deleted": False})


def create_kb_and_agent(api: ApiClient, allocator: NameAllocator, tracker: dict[str, list[dict[str, Any]]], purpose: str) -> tuple[str, dict[str, Any]]:
    name = allocator.next()
    api.create_kb(name)
    api.switch_kb(name)
    agent_resp = api.create_agent(name)
    agent = agent_resp.get("agent", {})
    track_kb(tracker, name, purpose)
    track_agent(tracker, agent, name, purpose)
    return name, agent


def build_result(name: str, category: str) -> dict[str, Any]:
    return {"name": name, "category": category, "started_at": now_iso(), "checks": []}


def scenario_result(name: str, strategy: str, sample: dict[str, Any]) -> dict[str, Any]:
    result = build_result(name, "scenario")
    result["strategy"] = strategy
    result["file_type"] = sample["file_type"]
    result["sample_path"] = str(sample["path"])
    return result


def probe_result(name: str) -> dict[str, Any]:
    return build_result(name, "probe")


def chunk_metadata_report(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    if not chunks:
        return {"complete": False, "checked": 0, "issues": [{"chunk_index": None, "missing_fields": sorted(CHUNK_REQUIRED_FIELDS)}]}
    issues: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks):
        missing = sorted(field for field in CHUNK_REQUIRED_FIELDS if field not in chunk)
        if missing:
            issues.append({"chunk_index": idx, "missing_fields": missing})
            if len(issues) >= 10:
                break
    return {
        "complete": not issues,
        "checked": len(chunks),
        "issues": issues,
        "first_chunk": chunks[0],
    }


def chunk_metadata_complete(chunks: list[dict[str, Any]]) -> bool:
    return chunk_metadata_report(chunks).get("complete", False)


def chunk_order_ok(chunks: list[dict[str, Any]]) -> bool:
    order = [int(item.get("chunk_order_index", 0) or 0) for item in chunks]
    return order == sorted(order)


def multimodal_evidence_report(chunks: list[dict[str, Any]], sample: dict[str, Any]) -> dict[str, Any]:
    target = sample["file_type"]
    signals = {
        "is_multimodal": 0,
        "original_type": 0,
        "modal_entity_name": 0,
        "media_reference": 0,
        "content_hint": 0,
    }
    content_hits: list[str] = []
    for chunk in chunks:
        original = str(chunk.get("original_type") or "").lower()
        modal = str(chunk.get("modal_entity_name") or "").lower()
        if chunk.get("is_multimodal"):
            signals["is_multimodal"] += 1
        if original == target or original in {"image", "table", "equation", "video"}:
            signals["original_type"] += 1
        if modal and (target in modal or any(word in modal for word in ("image", "table", "equation", "video"))):
            signals["modal_entity_name"] += 1
        if chunk.get("media_path") or chunk.get("media_url"):
            signals["media_reference"] += 1
        content = str(chunk.get("content") or "").lower()
        if any(token in content for token in INLINE_MEDIA_HINTS):
            signals["content_hint"] += 1
            if len(content_hits) < 3:
                content_hits.append(str(chunk.get("content") or "")[:240])
    found = any(signals.values())
    return {
        "found": found,
        "file_type": target,
        "chunk_count": len(chunks),
        "signals": signals,
        "content_hits": content_hits,
    }


def has_multimodal_evidence(chunks: list[dict[str, Any]], sample: dict[str, Any]) -> bool:
    return multimodal_evidence_report(chunks, sample).get("found", False)


def scenario_checks(
    result: dict[str, Any],
    task: dict[str, Any],
    task_timeline: list[dict[str, Any]],
    doc: dict[str, Any],
    doc_timeline: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    stats: dict[str, Any],
    batch_stats: dict[str, Any],
    entities: dict[str, Any],
    graph: dict[str, Any],
    sample: dict[str, Any],
) -> None:
    metadata = chunk_metadata_report(chunks)
    multimodal = multimodal_evidence_report(chunks, sample)
    task_details = evidence_payload(task, result)
    doc_details = evidence_payload(doc, result)

    add_check(result, "task_has_id", bool(task.get("task_id")), task_details)
    add_check(result, "task_completed", task.get("status") == "completed", task_details)
    add_check(result, "task_phases_observed", bool(task_timeline), task_timeline, severity="warning")
    add_check(result, "document_completed", str(doc.get("status") or "") in DOC_SUCCESS, doc_details)
    add_check(result, "document_timeline_observed", bool(doc_timeline), doc_timeline, severity="warning")
    add_check(result, "chunks_non_empty", len(chunks) > 0, {"count": len(chunks)})
    add_check(result, "chunk_order_monotonic", chunk_order_ok(chunks), [item.get("chunk_order_index") for item in chunks[:20]])
    add_check(result, "chunk_metadata_complete", metadata.get("complete", False), metadata)
    add_check(result, "chunks_have_content", all(bool(str(item.get("content", "")).strip()) for item in chunks), {"sample_size": min(5, len(chunks))})
    add_check(result, "stats_documents_positive", int(stats.get("documents", 0) or 0) > 0, stats)
    add_check(result, "stats_chunks_positive", int(stats.get("chunks", 0) or 0) > 0, stats)
    add_check(result, "batch_stats_match", batch_stats == stats, {"single": stats, "batch": batch_stats})
    add_check(result, "entities_endpoint_responded", "entities" in entities, entities)
    add_check(result, "graph_endpoint_responded", "nodes" in graph and "edges" in graph, graph)
    add_check(
        result,
        "agent_bound_to_kb",
        str(result.get("agent", {}).get("kb_name", "")) == str(result.get("kb_name", "")),
        result.get("agent", {}),
    )
    if int(stats.get("entities", 0) or 0) > 0:
        add_check(result, "graph_has_nodes_when_entities_present", len(graph.get("nodes", [])) > 0, {"stats": stats, "node_count": len(graph.get("nodes", []))})
    else:
        add_check(result, "entity_free_graph_allowed", True, stats, severity="warning")
    if doc.get("status") == "failed" and len(chunks) > 0:
        add_check(
            result,
            "failed_document_retained_partial_chunks",
            False,
            {
                "document": doc_details,
                "chunks_total": len(chunks),
                "stats": stats,
            },
            severity="warning",
        )
    add_check(
        result,
        "multimodal_evidence",
        multimodal.get("found", False),
        multimodal,
        severity="warning",
    )


def run_scenario(
    api: ApiClient,
    allocator: NameAllocator,
    tracker: dict[str, list[dict[str, Any]]],
    strategy: str,
    sample: dict[str, Any],
    timeout: float,
    poll_interval: float,
    server_log: Path | None = None,
) -> dict[str, Any]:
    result = scenario_result(f"{sample['file_type']}-{strategy}", strategy, sample)
    start_offset = log_offset(server_log)
    kb_name, agent = create_kb_and_agent(api, allocator, tracker, result["name"])
    result["kb_name"] = kb_name
    result["agent"] = {"id": agent.get("id"), "name": agent.get("name"), "kb_name": kb_name}
    upload_path = isolated_upload_copy(Path(sample["path"]))
    result["upload_sample_path"] = str(upload_path)

    try:
        upload = api.upload_file(kb_name, upload_path, strategy, sample["toggles"])
        task_id = str(upload.get("task_id") or "")
        result["upload"] = upload
        task, task_timeline, task_elapsed = wait_for_task(api, kb_name, task_id, timeout, poll_interval)
        doc, doc_timeline, doc_elapsed, doc_wait_error = wait_for_document_or_placeholder(
            api,
            kb_name,
            sample["path"].name,
            min(timeout, DOCUMENT_SETTLE_CAP_SECONDS),
            poll_interval,
        )
        doc_id = doc_id_of(doc)
        chunk_data = api.chunks(kb_name, doc_id) if doc_id else {"doc_id": "", "chunks": [], "total": 0}
        stats = api.stats(kb_name)
        batch = api.batch_stats([kb_name]).get("stats", {}).get(kb_name, {})
        entities = api.entities(kb_name)
        graph = api.graph(kb_name)

        result["task"] = task
        result["task_timeline"] = task_timeline
        result["task_elapsed_seconds"] = task_elapsed
        result["document"] = doc
        result["document_timeline"] = doc_timeline
        result["document_elapsed_seconds"] = doc_elapsed
        if doc_wait_error:
            result["document_wait_error"] = doc_wait_error
        result["chunks_total"] = chunk_data.get("total", 0)
        result["chunks_preview"] = chunk_data.get("chunks", [])[:5]
        result["stats"] = stats
        result["batch_stats"] = batch
        result["entities_total"] = entities.get("total", 0)
        result["graph_node_count"] = len(graph.get("nodes", []))
        result["graph_edge_count"] = len(graph.get("edges", []))
        attach_log_evidence(result, server_log, start_offset)

        scenario_checks(
            result,
            task,
            task_timeline,
            doc,
            doc_timeline,
            chunk_data.get("chunks", []),
            stats,
            batch,
            entities,
            graph,
            sample,
        )

        nodes = graph.get("nodes", [])
        if nodes:
            node_name = str(nodes[0].get("id") or nodes[0].get("label") or "")
            try:
                result["graph_node_detail"] = api.graph_node(kb_name, node_name)
                add_check(result, "graph_node_detail_readable", True, result["graph_node_detail"], severity="warning")
            except Exception as exc:
                add_check(result, "graph_node_detail_readable", False, str(exc), severity="warning")

        return finish(result)
    finally:
        cleanup_temp_path(upload_path)


def run_duplicate_probe(
    api: ApiClient,
    allocator: NameAllocator,
    tracker: dict[str, list[dict[str, Any]]],
    sample: dict[str, Any],
    timeout: float,
    poll_interval: float,
    server_log: Path | None = None,
) -> dict[str, Any]:
    result = probe_result("duplicate-upload-protection")
    start_offset = log_offset(server_log)
    kb_name, agent = create_kb_and_agent(api, allocator, tracker, result["name"])
    result["kb_name"] = kb_name
    result["agent_id"] = agent.get("id")
    upload_path = isolated_upload_copy(Path(sample["path"]))
    result["upload_sample_path"] = str(upload_path)

    try:
        first = api.upload_file(kb_name, upload_path, "fixed_size", sample["toggles"])
        result["first_upload"] = first
        try:
            api.upload_file(kb_name, upload_path, "fixed_size", sample["toggles"], expected=(409,))
            add_check(result, "duplicate_upload_rejected", True, "409 conflict observed")
        except Exception as exc:
            add_check(result, "duplicate_upload_rejected", False, str(exc), severity="warning")

        task_id = str(first.get("task_id") or "")
        task, timeline, _elapsed = wait_for_task(api, kb_name, task_id, timeout, poll_interval)
        result["task"] = task
        result["task_timeline"] = timeline
        attach_log_evidence(result, server_log, start_offset)
        return finish(result)
    finally:
        cleanup_temp_path(upload_path)


def run_delete_probe(
    api: ApiClient,
    allocator: NameAllocator,
    tracker: dict[str, list[dict[str, Any]]],
    sample: dict[str, Any],
    timeout: float,
    poll_interval: float,
    server_log: Path | None = None,
) -> dict[str, Any]:
    result = probe_result("download-delete-lifecycle")
    start_offset = log_offset(server_log)
    kb_name, agent = create_kb_and_agent(api, allocator, tracker, result["name"])
    result["kb_name"] = kb_name
    result["agent_id"] = agent.get("id")
    upload_path = isolated_upload_copy(Path(sample["path"]))
    result["upload_sample_path"] = str(upload_path)

    try:
        upload = api.upload_file(kb_name, upload_path, "fixed_size", sample["toggles"])
        task_id = str(upload.get("task_id") or "")
        task, timeline, _elapsed = wait_for_task(api, kb_name, task_id, timeout, poll_interval)
        doc, doc_timeline, _doc_elapsed, doc_wait_error = wait_for_document_or_placeholder(
            api,
            kb_name,
            sample["path"].name,
            min(timeout, DOCUMENT_SETTLE_CAP_SECONDS),
            poll_interval,
        )
        doc_id = doc_id_of(doc)
        if doc_wait_error:
            result["document_wait_error"] = doc_wait_error
        if not doc_id:
            attach_log_evidence(result, server_log, start_offset)
            add_check(result, "document_visible_after_task", False, evidence_payload(doc, result))
            result["task"] = task
            result["task_timeline"] = timeline
            result["document_timeline"] = doc_timeline
            return finish(result)

        response, content = api.download_document(kb_name, doc_id)
        result["download"] = {
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "bytes": len(content),
        }
        add_check(result, "document_downloadable", response.status_code == 200 and len(content) > 0, result["download"])

        delete_started = time.monotonic()
        delete_resp = api.delete_document(kb_name, doc_id)
        delete_elapsed = round(time.monotonic() - delete_started, 2)
        result["delete_response"] = delete_resp
        result["delete_elapsed_seconds"] = delete_elapsed
        add_check(
            result,
            "delete_response_within_budget",
            delete_elapsed <= min(DELETE_RESPONSE_BUDGET_SECONDS, timeout),
            {
                "elapsed_seconds": delete_elapsed,
                "budget_seconds": min(DELETE_RESPONSE_BUDGET_SECONDS, timeout),
            },
            severity="warning",
        )
        deleted = wait_for_absence(api, kb_name, sample["path"].name, timeout, poll_interval)
        add_check(result, "document_removed_after_delete", deleted, {"filename": sample["path"].name})
        result["task"] = task
        result["task_timeline"] = timeline
        result["document_timeline"] = doc_timeline
        attach_log_evidence(result, server_log, start_offset)
        return finish(result)
    finally:
        cleanup_temp_path(upload_path)


def run_retry_probe(
    api: ApiClient,
    allocator: NameAllocator,
    tracker: dict[str, list[dict[str, Any]]],
    timeout: float,
    poll_interval: float,
    server_log: Path | None = None,
) -> dict[str, Any]:
    result = probe_result("failed-document-retry")
    start_offset = log_offset(server_log)
    kb_name, agent = create_kb_and_agent(api, allocator, tracker, result["name"])
    result["kb_name"] = kb_name
    result["agent_id"] = agent.get("id")

    with tempfile.NamedTemporaryFile(prefix="kb-regression-", suffix=".pdf", delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write(b"not-a-real-pdf")

    try:
        upload = api.upload_file(
            kb_name,
            temp_path,
            "fixed_size",
            {
                "enable_image": True,
                "enable_table": True,
                "enable_equation": True,
                "enable_video": False,
            },
        )
        task_id = str(upload.get("task_id") or "")
        task, timeline, _elapsed = wait_for_task(api, kb_name, task_id, timeout, poll_interval)
        result["task"] = task
        result["task_timeline"] = timeline
        if task.get("status") != "failed":
            add_check(result, "synthetic_invalid_pdf_failed", False, task, severity="warning")
            attach_log_evidence(result, server_log, start_offset)
            return finish(result)

        doc, doc_timeline, _doc_elapsed, doc_wait_error = wait_for_document_or_placeholder(
            api,
            kb_name,
            temp_path.name,
            min(timeout, DOCUMENT_SETTLE_CAP_SECONDS),
            poll_interval,
        )
        result["document_timeline"] = doc_timeline
        if doc_wait_error:
            result["document_wait_error"] = doc_wait_error
        if doc.get("status") != "failed":
            add_check(result, "failed_doc_visible", False, doc, severity="warning")
            attach_log_evidence(result, server_log, start_offset)
            return finish(result)

        retry = api.retry_document(kb_name, doc_id_of(doc))
        result["retry"] = retry
        add_check(result, "retry_endpoint_accepts_failed_doc", retry.get("status") == "queued", retry, severity="warning")
        attach_log_evidence(result, server_log, start_offset)
        return finish(result)
    finally:
        temp_path.unlink(missing_ok=True)


def run_multimodal_reprocess_probe(
    api: ApiClient,
    allocator: NameAllocator,
    tracker: dict[str, list[dict[str, Any]]],
    server_log: Path | None = None,
) -> dict[str, Any]:
    result = probe_result("multimodal-reprocess-admin")
    start_offset = log_offset(server_log)
    kb_name, agent = create_kb_and_agent(api, allocator, tracker, result["name"])
    result["kb_name"] = kb_name
    result["agent_id"] = agent.get("id")
    response = api.reprocess_multimodal(kb_name)
    result["response"] = response
    add_check(
        result,
        "admin_reprocess_endpoint_responds",
        str(response.get("status", "")) in {"ok", "queued"},
        response,
    )
    attach_log_evidence(result, server_log, start_offset)
    return finish(result)


def run_vision_embedding_health_probe(
    api: ApiClient, server_log: Path | None = None
) -> dict[str, Any]:
    result = probe_result("vision-embedding-health")
    start_offset = log_offset(server_log)
    response = api.vision_embedding_health()
    result["response"] = response
    available = response.get("status") == "ok" and bool(response.get("available"))
    classification = None
    if not available:
        classification = {
            "kind": "environment",
            "code": "vision_embedding_auth_blocked",
            "summary": "Vision embedding is blocked by provider credentials or entitlement.",
        }
    add_check(
        result,
        "vision_embedding_authorized",
        available,
        response,
        severity="warning",
        classification=classification,
    )
    attach_log_evidence(result, server_log, start_offset)
    return finish(result)


def role_by_name(roles: list[dict[str, Any]], role_name: str) -> dict[str, Any] | None:
    for role in roles:
        if str(role.get("name", "")) == role_name:
            return role
    return None


def run_rbac_probe(
    admin_api: ApiClient,
    base_url: str,
    allocator: NameAllocator,
    tracker: dict[str, list[dict[str, Any]]],
    server_log: Path | None = None,
) -> dict[str, Any]:
    result = probe_result("rbac-negative-check")
    start_offset = log_offset(server_log)
    try:
        roles = admin_api.roles().get("roles", [])
    except Exception as exc:
        add_check(result, "roles_accessible", False, {"error": str(exc)})
        attach_log_evidence(result, server_log, start_offset)
        return finish(result)

    result["roles"] = [str(role.get("name", "")) for role in roles]
    missing_roles = [name for name in RBAC_REQUIRED_ROLES if not role_by_name(roles, name)]
    add_check(result, "rbac_v2_roles_available", not missing_roles, {"missing": missing_roles, "roles": result["roles"]})
    if missing_roles:
        attach_log_evidence(result, server_log, start_offset)
        return finish(result)

    password = "Codex!2345"
    student_role = role_by_name(roles, "student")
    teacher_role = role_by_name(roles, "teacher")
    super_admin_role = role_by_name(roles, "super_admin")
    matrix: dict[str, Any] = {}

    student_username = allocator.next() + "_student"
    student_resp = admin_api.create_user(student_username, f"{student_username}@example.com", password, int(student_role["id"]))
    student_user = student_resp.get("user", {})
    track_user(tracker, student_user, result["name"])
    matrix["student"] = {
        "role": student_role,
        "user": {"id": student_user.get("id"), "username": student_user.get("username")},
    }

    student_api = ApiClient(base_url, 30.0)
    try:
        student_api.login(student_username, password)
        student_create_kb_name = allocator.next()
        student_denied = False
        try:
            student_api.create_kb(student_create_kb_name)
            track_kb(tracker, student_create_kb_name, result["name"])
            matrix["student"]["unexpected_kb"] = student_create_kb_name
        except Exception as exc:
            student_denied = True
            matrix["student"]["create_kb_error"] = str(exc)
        add_check(
            result,
            "student_kb_write_denied",
            student_denied,
            {"role": "student", "error": matrix["student"].get("create_kb_error", "")},
        )

        student_list = student_api.kbs()
        matrix["student"]["kb_list"] = student_list
        add_check(
            result,
            "student_kb_list_stays_empty",
            student_list.get("knowledge_bases") == [],
            student_list,
        )

        student_reprocess_denied = False
        try:
            student_api.reprocess_multimodal("test-permission-sentinel", expected=(403,))
            student_reprocess_denied = True
        except Exception as exc:
            matrix["student"]["reprocess_error"] = str(exc)
        add_check(
            result,
            "student_admin_reprocess_denied",
            student_reprocess_denied,
            {"role": "student", "error": matrix["student"].get("reprocess_error", ""), "endpoint": "/kb/{kb_name}/reprocess-multimodal"},
        )
    finally:
        student_api.close()

    teacher_username = allocator.next() + "_teacher"
    teacher_resp = admin_api.create_user(teacher_username, f"{teacher_username}@example.com", password, int(teacher_role["id"]))
    teacher_user = teacher_resp.get("user", {})
    track_user(tracker, teacher_user, result["name"])
    matrix["teacher"] = {
        "role": teacher_role,
        "user": {"id": teacher_user.get("id"), "username": teacher_user.get("username")},
    }

    teacher_api = ApiClient(base_url, 30.0)
    try:
        teacher_api.login(teacher_username, password)
        teacher_kb_name = allocator.next()
        teacher_create_ok = False
        try:
            create_resp = teacher_api.create_kb(teacher_kb_name)
            teacher_create_ok = create_resp.get("status") == "created"
            matrix["teacher"]["create_kb_response"] = create_resp
            if teacher_create_ok:
                track_kb(tracker, teacher_kb_name, result["name"])
        except Exception as exc:
            matrix["teacher"]["create_kb_error"] = str(exc)
        add_check(
            result,
            "teacher_kb_write_allowed",
            teacher_create_ok,
            {
                "role": "teacher",
                "kb_name": teacher_kb_name,
                "response": matrix["teacher"].get("create_kb_response"),
                "error": matrix["teacher"].get("create_kb_error", ""),
            },
        )

        teacher_reprocess_denied = False
        try:
            teacher_api.reprocess_multimodal(teacher_kb_name if teacher_create_ok else "test-permission-sentinel", expected=(403,))
            teacher_reprocess_denied = True
        except Exception as exc:
            matrix["teacher"]["reprocess_error"] = str(exc)
        add_check(
            result,
            "teacher_admin_reprocess_denied",
            teacher_reprocess_denied,
            {"role": "teacher", "error": matrix["teacher"].get("reprocess_error", ""), "endpoint": "/kb/{kb_name}/reprocess-multimodal"},
        )
    finally:
        teacher_api.close()

    matrix["super_admin"] = {
        "role": super_admin_role,
        "user": admin_api.auth_me().get("user", {}),
    }

    admin_kb_name = allocator.next()
    admin_create_ok = False
    try:
        admin_create_resp = admin_api.create_kb(admin_kb_name)
        admin_create_ok = admin_create_resp.get("status") == "created"
        matrix["super_admin"]["create_kb_response"] = admin_create_resp
        if admin_create_ok:
            track_kb(tracker, admin_kb_name, result["name"])
    except Exception as exc:
        matrix["super_admin"]["create_kb_error"] = str(exc)
    add_check(
        result,
        "super_admin_kb_write_allowed",
        admin_create_ok,
        {
            "role": "super_admin",
            "kb_name": admin_kb_name,
            "response": matrix["super_admin"].get("create_kb_response"),
            "error": matrix["super_admin"].get("create_kb_error", ""),
        },
    )

    admin_reprocess_ok = False
    if admin_create_ok:
        try:
            reprocess_resp = admin_api.reprocess_multimodal(admin_kb_name)
            matrix["super_admin"]["reprocess_response"] = reprocess_resp
            admin_reprocess_ok = str(reprocess_resp.get("status", "")) in {"ok", "queued"}
        except Exception as exc:
            matrix["super_admin"]["reprocess_error"] = str(exc)
    add_check(
        result,
        "super_admin_reprocess_allowed",
        admin_reprocess_ok,
        {
            "role": "super_admin",
            "kb_name": admin_kb_name,
            "response": matrix["super_admin"].get("reprocess_response"),
            "error": matrix["super_admin"].get("reprocess_error", ""),
            "endpoint": "/kb/{kb_name}/reprocess-multimodal",
        },
    )

    result["matrix"] = matrix
    attach_log_evidence(result, server_log, start_offset)
    return finish(result)


def add_runtime_error(
    result: dict[str, Any],
    check_name: str,
    exc: Exception,
    server_log: Path | None,
    start_offset: int,
    severity: str = "error",
) -> dict[str, Any]:
    attach_log_evidence(result, server_log, start_offset)
    details: dict[str, Any] = {"error": str(exc)}
    if result.get("server_log_clues"):
        details["server_log_clues"] = result["server_log_clues"]
    if result.get("server_log_path"):
        details["server_log_path"] = result["server_log_path"]
    add_check(result, check_name, False, details, severity=severity)
    return finish(result)


def collect_issue_summary(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: dict[str, dict[str, Any]] = {}
    for result in results:
        for check in result.get("checks", []):
            if check.get("passed"):
                continue
            classification = check.get("classification")
            if not classification:
                continue
            code = str(classification.get("code"))
            bucket = issues.setdefault(
                code,
                {
                    "code": code,
                    "kind": classification.get("kind"),
                    "summary": classification.get("summary"),
                    "count": 0,
                    "results": [],
                    "checks": [],
                },
            )
            bucket["count"] += 1
            if result.get("name") not in bucket["results"]:
                bucket["results"].append(result.get("name"))
            if check.get("name") not in bucket["checks"]:
                bucket["checks"].append(check.get("name"))
    return sorted(issues.values(), key=lambda item: (-int(item.get("count", 0) or 0), str(item.get("code", ""))))


def cleanup_resources(api: ApiClient, tracker: dict[str, list[dict[str, Any]]]) -> None:
    for agent in reversed(tracker["agents"]):
        if agent.get("deleted") or not agent.get("id"):
            continue
        try:
            api.delete_agent(str(agent["id"]))
            agent["deleted"] = True
        except Exception:
            pass
    for user in reversed(tracker["users"]):
        if user.get("deleted") or user.get("id") is None:
            continue
        try:
            api.delete_user(int(user["id"]))
            user["deleted"] = True
        except Exception:
            pass
    for kb in reversed(tracker["kbs"]):
        if kb.get("deleted"):
            continue
        try:
            api.delete_kb(str(kb["name"]))
            kb["deleted"] = True
        except Exception:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Knowledge base regression suite")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--profile", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--strategy", action="append", default=[])
    parser.add_argument("--file-type", action="append", default=[])
    parser.add_argument("--docx", default=str(DEFAULT_DOCX))
    parser.add_argument("--pdf", default=str(DEFAULT_PDF))
    parser.add_argument("--video", default=str(DEFAULT_VIDEO))
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--server-log", default="")
    parser.add_argument("--skip-scenarios", action="store_true")
    parser.add_argument("--skip-probes", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    samples = build_samples(Path(args.docx), Path(args.pdf), Path(args.video))
    preflight(samples)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    server_log = Path(args.server_log) if args.server_log else None

    api = ApiClient(args.base_url, args.timeout)
    tracker = create_tracker()
    started_at = now_iso()
    try:
        api.login(args.username, args.password)
        me = api.auth_me().get("user", {})
        used = used_test_names(api.kbs(), api.agents())
        allocator = NameAllocator(used)

        scenarios: list[dict[str, Any]] = []
        if not args.skip_scenarios:
            for strategy, file_type in matrix(args.profile, args.strategy, args.file_type):
                sample = samples[file_type]
                sample["file_type"] = file_type
                start_offset = log_offset(server_log)
                try:
                    scenarios.append(run_scenario(api, allocator, tracker, strategy, sample, args.timeout, args.poll_interval, server_log))
                except Exception as exc:
                    failed = scenario_result(f"{file_type}-{strategy}", strategy, sample)
                    scenarios.append(add_runtime_error(failed, "scenario_runtime_error", exc, server_log, start_offset))

        probes: list[dict[str, Any]] = []
        if not args.skip_probes:
            start_offset = log_offset(server_log)
            try:
                probes.append(run_duplicate_probe(api, allocator, tracker, samples["pdf"], args.timeout, args.poll_interval, server_log))
            except Exception as exc:
                probe = probe_result("duplicate-upload-protection")
                probes.append(add_runtime_error(probe, "probe_runtime_error", exc, server_log, start_offset))

            start_offset = log_offset(server_log)
            try:
                probes.append(run_delete_probe(api, allocator, tracker, samples["docx"], args.timeout, args.poll_interval, server_log))
            except Exception as exc:
                probe = probe_result("download-delete-lifecycle")
                probes.append(add_runtime_error(probe, "probe_runtime_error", exc, server_log, start_offset))

            start_offset = log_offset(server_log)
            try:
                probes.append(run_retry_probe(api, allocator, tracker, args.timeout, args.poll_interval, server_log))
            except Exception as exc:
                probe = probe_result("failed-document-retry")
                probes.append(add_runtime_error(probe, "probe_runtime_error", exc, server_log, start_offset))

            start_offset = log_offset(server_log)
            try:
                probes.append(run_multimodal_reprocess_probe(api, allocator, tracker, server_log))
            except Exception as exc:
                probe = probe_result("multimodal-reprocess-admin")
                probes.append(add_runtime_error(probe, "probe_runtime_error", exc, server_log, start_offset))

            start_offset = log_offset(server_log)
            try:
                probes.append(run_vision_embedding_health_probe(api, server_log))
            except Exception as exc:
                probe = probe_result("vision-embedding-health")
                probes.append(add_runtime_error(probe, "probe_runtime_error", exc, server_log, start_offset, severity="warning"))

            start_offset = log_offset(server_log)
            try:
                probes.append(run_rbac_probe(api, args.base_url, allocator, tracker, server_log))
            except Exception as exc:
                probe = probe_result("rbac-negative-check")
                probes.append(add_runtime_error(probe, "probe_runtime_error", exc, server_log, start_offset, severity="warning"))

        all_results = scenarios + probes
        report = {
            "started_at": started_at,
            "finished_at": now_iso(),
            "base_url": norm_url(args.base_url),
            "profile": args.profile,
            "actor": {"id": me.get("id"), "username": me.get("username"), "is_admin": me.get("is_admin")},
            "samples": {name: str(item["path"]) for name, item in samples.items()},
            "server_log": str(server_log) if server_log else "",
            "scenario_count": len(scenarios),
            "probe_count": len(probes),
            "counts": group_counts(all_results),
            "issue_summary": collect_issue_summary(all_results),
            "scenarios": scenarios,
            "probes": probes,
            "resources": tracker,
        }

        report_path = output_dir / f"kb-regression-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[kb-regression] report: {report_path}")
        print(json.dumps(report["counts"], ensure_ascii=False))

        if args.cleanup:
            cleanup_resources(api, tracker)
            report["resources_after_cleanup"] = tracker
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        return 0 if report["counts"]["failed"] == 0 and report["counts"]["blocked"] == 0 else 1
    finally:
        api.close()


if __name__ == "__main__":
    sys.exit(main())

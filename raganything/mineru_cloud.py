from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from lightrag.utils import compute_mdhash_id


logger = logging.getLogger(__name__)


@dataclass
class MinerUCloudConfig:
    api_key: str
    base_url: str = "https://mineru.net"
    model_version: str = "vlm"
    language: str = "en"
    enable_formula: bool = True
    enable_table: bool = True
    is_ocr: bool = False
    extra_formats: Optional[List[str]] = None
    poll_interval_sec: int = 5
    timeout_sec: int = 1800


class MinerUPrecisionCloudClient:
    def __init__(self, config: MinerUCloudConfig):
        self.config = config

    @staticmethod
    def _require_requests():
        try:
            import requests  # type: ignore

            return requests
        except Exception as exc:
            raise RuntimeError(
                "requests is required for MinerU cloud API support. "
                "Install it with `pip install requests`."
            ) from exc

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "*/*",
        }

    def _build_upload_request(self, file_path: Path) -> Dict[str, Any]:
        digest = hashlib.md5(str(file_path.resolve()).encode("utf-8")).hexdigest()[:12]
        data_id = f"{file_path.stem}-{digest}"
        file_item: Dict[str, Any] = {
            "name": file_path.name,
            "data_id": data_id,
            "is_ocr": self.config.is_ocr,
        }
        payload: Dict[str, Any] = {
            "files": [file_item],
            "model_version": self.config.model_version,
            "language": self.config.language,
            "enable_formula": self.config.enable_formula,
            "enable_table": self.config.enable_table,
        }
        if self.config.extra_formats:
            payload["extra_formats"] = list(self.config.extra_formats)
        return payload

    def _create_upload_task(self, file_path: Path) -> Tuple[str, str, str, Dict[str, Any]]:
        requests = self._require_requests()
        url = f"{self.config.base_url.rstrip('/')}/api/v4/file-urls/batch"
        payload = self._build_upload_request(file_path)
        logger.info("Submitting MinerU cloud upload task for %s", file_path.name)
        response = requests.post(url, headers=self._headers(), json=payload, timeout=60)
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 0:
            raise RuntimeError(f"MinerU cloud upload-url request failed: {body}")
        data = body.get("data") or {}
        batch_id = data.get("batch_id")
        file_urls = data.get("file_urls") or []
        if not batch_id or not file_urls:
            raise RuntimeError(f"MinerU cloud upload-url response missing fields: {body}")
        file_url = file_urls[0]
        data_id = payload["files"][0]["data_id"]
        return batch_id, data_id, file_url, body

    def _upload_file(self, file_path: Path, file_url: str) -> None:
        requests = self._require_requests()
        with open(file_path, "rb") as f:
            response = requests.put(file_url, data=f, timeout=600)
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"MinerU cloud file upload failed: HTTP {response.status_code}"
            )

    def _poll_result(self, batch_id: str, data_id: str, file_name: str) -> Dict[str, Any]:
        requests = self._require_requests()
        url = f"{self.config.base_url.rstrip('/')}/api/v4/extract-results/batch/{batch_id}"
        deadline = time.time() + self.config.timeout_sec
        latest_body: Dict[str, Any] = {}

        while time.time() < deadline:
            response = requests.get(url, headers=self._headers(), timeout=60)
            response.raise_for_status()
            body = response.json()
            latest_body = body
            if body.get("code") != 0:
                raise RuntimeError(f"MinerU cloud poll failed: {body}")

            result_items = ((body.get("data") or {}).get("extract_result") or [])
            target = None
            for item in result_items:
                if item.get("data_id") == data_id or item.get("file_name") == file_name:
                    target = item
                    break

            if target is None:
                time.sleep(self.config.poll_interval_sec)
                continue

            state = target.get("state")
            if state == "done":
                return target
            if state == "failed":
                raise RuntimeError(
                    f"MinerU cloud extract failed: {target.get('err_msg', 'Unknown error')}"
                )

            time.sleep(self.config.poll_interval_sec)

        raise TimeoutError(
            f"MinerU cloud polling timed out after {self.config.timeout_sec}s: {latest_body}"
        )

    @staticmethod
    def _fix_content_list_paths(content_list: List[Dict[str, Any]], base_dir: Path) -> List[Dict[str, Any]]:
        for item in content_list:
            if not isinstance(item, dict):
                continue
            for field_name in ["img_path", "table_img_path", "equation_img_path"]:
                raw_value = item.get(field_name)
                if not raw_value:
                    continue
                candidate = Path(str(raw_value))
                if candidate.is_absolute():
                    continue
                absolute = (base_dir / candidate).resolve()
                item[field_name] = str(absolute)
        return content_list

    @staticmethod
    def _load_result_from_artifacts(artifact_dir: Path) -> Tuple[List[Dict[str, Any]], str]:
        json_candidates = sorted(artifact_dir.rglob("*_content_list.json")) + sorted(
            artifact_dir.rglob("*_content_list_v2.json")
        )
        if not json_candidates:
            raise RuntimeError(f"MinerU cloud result missing content_list json under {artifact_dir}")
        json_path = json_candidates[0]

        md_candidates = [p for p in artifact_dir.rglob("full.md")]
        if not md_candidates:
            md_candidates = [p for p in artifact_dir.rglob("*.md")]
        md_content = ""
        if md_candidates:
            md_content = md_candidates[0].read_text(encoding="utf-8", errors="ignore")

        with open(json_path, "r", encoding="utf-8") as f:
            content_list = json.load(f)
        content_list = MinerUPrecisionCloudClient._fix_content_list_paths(content_list, json_path.parent)
        return content_list, md_content

    @staticmethod
    def _generate_doc_id(content_list: List[Dict[str, Any]]) -> str:
        content_parts: List[str] = []
        for item in content_list:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type", "")
            if item_type == "text" and item.get("text"):
                content_parts.append(str(item["text"]).strip())
            elif item_type == "table" and item.get("table_body"):
                content_parts.append(str(item["table_body"]))
            elif item_type == "equation" and item.get("text"):
                content_parts.append(f"equation:{item['text']}")
            elif item_type == "image" and item.get("img_path"):
                content_parts.append(f"image:{item['img_path']}")
        return compute_mdhash_id("\n".join(content_parts), prefix="doc-")

    def parse_file(
        self,
        file_path: Path,
        parser_output_dir: Path,
        artifact_subdir: str = "mineru_cloud",
    ) -> Tuple[List[Dict[str, Any]], str]:
        requests = self._require_requests()
        parser_output_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir = parser_output_dir / file_path.stem / artifact_subdir
        artifact_dir.mkdir(parents=True, exist_ok=True)

        batch_id, data_id, upload_url, submit_response = self._create_upload_task(file_path)
        (artifact_dir / "submit_response.json").write_text(
            json.dumps(submit_response, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._upload_file(file_path, upload_url)
        poll_result = self._poll_result(batch_id, data_id, file_path.name)
        (artifact_dir / "poll_result.json").write_text(
            json.dumps(poll_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        full_zip_url = poll_result.get("full_zip_url")
        if not full_zip_url:
            raise RuntimeError(f"MinerU cloud result missing full_zip_url: {poll_result}")

        zip_path = artifact_dir / "result.zip"
        response = requests.get(full_zip_url, timeout=600)
        response.raise_for_status()
        zip_path.write_bytes(response.content)

        extract_dir = artifact_dir / "result"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        content_list, md_content = self._load_result_from_artifacts(extract_dir)
        if md_content:
            (artifact_dir / "full.md").write_text(md_content, encoding="utf-8")
        doc_id = self._generate_doc_id(content_list)
        return content_list, doc_id


class MineruCloudParser:
    """Official MinerU Precision Extract cloud API parser adapter."""

    OFFICE_FORMATS = {".doc", ".docx", ".ppt", ".pptx"}
    IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"}
    HTML_FORMATS = {".html", ".htm"}
    TEXT_FORMATS: set[str] = set()

    def __init__(self) -> None:
        pass

    @staticmethod
    def _env(key: str, default: str = "") -> str:
        return os.getenv(key, default)

    def _build_config(self, lang: Optional[str] = None, **kwargs) -> MinerUCloudConfig:
        api_key = str(kwargs.get("api_key") or self._env("MINERU_API_KEY", "")).strip()
        if not api_key:
            raise RuntimeError(
                "MINERU_API_KEY is missing. Set it in the environment or pass api_key in parser_kwargs."
            )

        base_url = str(
            kwargs.get("api_base_url")
            or kwargs.get("base_url")
            or self._env("MINERU_API_BASE_URL", "https://mineru.net")
        ).strip()
        model_version = str(
            kwargs.get("model_version") or self._env("MINERU_CLOUD_MODEL_VERSION", "vlm")
        ).strip()
        language = str(
            kwargs.get("language")
            or lang
            or kwargs.get("lang")
            or self._env("MINERU_CLOUD_LANGUAGE", "en")
        ).strip()

        return MinerUCloudConfig(
            api_key=api_key,
            base_url=base_url,
            model_version=model_version or "vlm",
            language=language or "en",
            enable_formula=bool(kwargs.get("enable_formula", kwargs.get("formula", True))),
            enable_table=bool(kwargs.get("enable_table", kwargs.get("table", True))),
            is_ocr=bool(kwargs.get("is_ocr", False)),
            extra_formats=list(kwargs.get("extra_formats", [])) or None,
            poll_interval_sec=int(
                kwargs.get(
                    "poll_interval_sec",
                    self._env("MINERU_CLOUD_POLL_INTERVAL_SEC", "5"),
                )
            ),
            timeout_sec=int(
                kwargs.get(
                    "timeout_sec",
                    self._env("MINERU_CLOUD_TIMEOUT_SEC", "1800"),
                )
            ),
        )

    def parse_pdf(
        self,
        pdf_path: Union[str, Path],
        output_dir: Optional[str] = None,
        method: str = "api",
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")

        if output_dir:
            base_output_dir = Path(output_dir)
        else:
            base_output_dir = pdf_path.parent / "mineru_cloud_output"
        base_output_dir.mkdir(parents=True, exist_ok=True)

        config = self._build_config(lang=lang, **kwargs)
        client = MinerUPrecisionCloudClient(config)
        content_list, _ = client.parse_file(
            file_path=pdf_path,
            parser_output_dir=base_output_dir,
            artifact_subdir="mineru_cloud",
        )
        return content_list

    def parse_image(
        self,
        image_path: Union[str, Path],
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        image_path = Path(image_path)
        if image_path.suffix.lower() not in self.IMAGE_FORMATS:
            raise ValueError(f"Unsupported image format for MinerU cloud: {image_path.suffix}")
        return self.parse_pdf(image_path, output_dir=output_dir, method="api", lang=lang, **kwargs)

    def parse_office_doc(
        self,
        doc_path: Union[str, Path],
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        doc_path = Path(doc_path)
        ext = doc_path.suffix.lower()
        if ext not in (self.OFFICE_FORMATS | self.HTML_FORMATS):
            raise ValueError(f"Unsupported office/html format for MinerU cloud: {doc_path.suffix}")
        local_kwargs = dict(kwargs)
        if ext in self.HTML_FORMATS and str(local_kwargs.get("model_version", "") or "").strip().lower() in {"", "vlm"}:
            local_kwargs["model_version"] = "MinerU-HTML"
        return self.parse_pdf(doc_path, output_dir=output_dir, method="api", lang=lang, **local_kwargs)

    def parse_document(
        self,
        file_path: Union[str, Path],
        method: str = "api",
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        file_path = Path(file_path)
        ext = file_path.suffix.lower()
        if ext == ".pdf":
            return self.parse_pdf(file_path, output_dir=output_dir, method=method, lang=lang, **kwargs)
        if ext in self.IMAGE_FORMATS:
            return self.parse_image(file_path, output_dir=output_dir, lang=lang, **kwargs)
        if ext in (self.OFFICE_FORMATS | self.HTML_FORMATS):
            return self.parse_office_doc(file_path, output_dir=output_dir, lang=lang, **kwargs)
        raise ValueError(
            "MinerU cloud parser supports local PDF, DOC, DOCX, PPT, PPTX, HTML, and image files "
            f"(png/jpg/jpeg/jp2/webp/gif/bmp); got: {file_path.suffix}"
        )

    def check_installation(self) -> bool:
        try:
            MinerUPrecisionCloudClient._require_requests()
            return True
        except Exception:
            return False


__all__ = ["MinerUCloudConfig", "MinerUPrecisionCloudClient", "MineruCloudParser"]

"""
Parse caching and output directory computation mixin for RAGAnything.

Encapsulates document cache keys, streaming fingerprints, content-based doc IDs,
and persistent parse cache storage.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from lightrag.utils import compute_mdhash_id

from raganything.asset_urls import MEDIA_PATH_FIELDS
from raganything.parse_options import relevant_parser_kwargs
from raganything.parser import Parser
from raganything.utils import resolve_document_images

AUDIO_FILE_EXTENSIONS = frozenset(
    {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".wma", ".aac", ".opus"}
)
VIDEO_FILE_EXTENSIONS = frozenset(
    {".mp4", ".mov", ".webm", ".avi", ".mkv", ".flv", ".wmv", ".m4v"}
)


class ProcessorCacheMixin:
    """Mixin responsible for document parse caching, fingerprints, and output tracking."""

    @staticmethod
    def _relevant_parser_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
        """Return parser options that change the persisted parse result."""
        return relevant_parser_kwargs(kwargs)

    @staticmethod
    def _file_content_fingerprint(file_path: Path) -> str:
        """Return a streaming SHA-256 fingerprint for parse-cache identity."""
        digest = hashlib.sha256()
        with file_path.open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _get_file_reference(self, file_path: str) -> str:
        """
        Get file reference based on use_full_path configuration.

        Args:
            file_path: Path to the file (can be absolute or relative)

        Returns:
            str: Full path if use_full_path is True, otherwise basename
        """
        if self.config.use_full_path:
            return str(file_path)
        else:
            return os.path.basename(file_path)

    def _generate_cache_key(
        self, file_path: Path, parse_method: str = None, **kwargs
    ) -> str:
        """
        Generate cache key based on file content, path, and parsing configuration

        Args:
            file_path: Path to the file
            parse_method: Parse method used
            **kwargs: Additional parser parameters

        Returns:
            str: Cache key for the file and configuration
        """
        mtime = file_path.stat().st_mtime

        config_dict = {
            "file_path": str(file_path.absolute()),
            "mtime": mtime,
            "file_sha256": self._file_content_fingerprint(file_path),
            "parser": self.config.parser,
            "parse_method": parse_method or self.config.parse_method,
        }
        if getattr(self.config, "merge_continued_tables", False):
            config_dict["merge_continued_tables"] = True

        config_dict.update(self._relevant_parser_kwargs(kwargs))

        config_str = json.dumps(config_dict, sort_keys=True)
        return hashlib.md5(config_str.encode()).hexdigest()

    def _generate_content_based_doc_id(self, content_list: list[dict[str, Any]]) -> str:
        """
        Generate doc_id based on document content

        Args:
            content_list: Parsed content list

        Returns:
            str: Content-based document ID with doc- prefix
        """
        content_hash_data = []

        for item in content_list:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    content_hash_data.append(item["text"].strip())
                elif item.get("type") == "image" and item.get("img_path"):
                    content_hash_data.append(f"image:{item['img_path']}")
                elif item.get("type") == "table" and item.get("table_body"):
                    content_hash_data.append(f"table:{item['table_body']}")
                elif item.get("type") == "equation" and item.get("text"):
                    content_hash_data.append(f"equation:{item['text']}")
                else:
                    content_hash_data.append(str(item))

        content_signature = "\n".join(content_hash_data)
        return compute_mdhash_id(content_signature, prefix="doc-")

    async def _get_cached_result(
        self, cache_key: str, file_path: Path, parse_method: str = None, **kwargs
    ) -> tuple[list[dict[str, Any]], str] | None:
        """
        Get cached parsing result if available and valid

        Args:
            cache_key: Cache key to look up
            file_path: Path to the file for mtime check
            parse_method: Parse method used
            **kwargs: Additional parser parameters

        Returns:
            tuple[List[Dict[str, Any]], str] | None: (content_list, doc_id) or None if not found/invalid
        """
        if not hasattr(self, "parse_cache") or self.parse_cache is None:
            return None

        try:
            cached_data = await self.parse_cache.get_by_id(cache_key)
            if not cached_data:
                return None

            current_mtime = file_path.stat().st_mtime
            cached_mtime = cached_data.get("mtime", 0)

            if current_mtime != cached_mtime:
                self.logger.debug(f"Cache invalid - file modified: {cache_key}")
                return None

            cached_config = cached_data.get("parse_config", {})
            current_config = {
                "parser": self.config.parser,
                "parse_method": parse_method or self.config.parse_method,
            }
            if getattr(self.config, "merge_continued_tables", False):
                current_config["merge_continued_tables"] = True

            current_config.update(self._relevant_parser_kwargs(kwargs))

            if cached_config != current_config:
                self.logger.debug(f"Cache invalid - config changed: {cache_key}")
                return None

            content_list = cached_data.get("content_list", [])
            doc_id = cached_data.get("doc_id")

            if content_list and doc_id:
                # Reparse legacy relative paths once so the cached ID and asset agree.
                if resolve_document_images(content_list, file_path) != content_list:
                    return None
                for item in content_list:
                    if not isinstance(item, dict):
                        continue
                    media_paths = [
                        item.get(field)
                        for field in (*MEDIA_PATH_FIELDS, "audio_path", "video_path")
                    ]
                    media_paths.extend(item.get("table_img_paths") or [])
                    for media_path in media_paths:
                        if not isinstance(media_path, str) or not media_path:
                            continue
                        if media_path.startswith(("http://", "https://", "s3://")):
                            continue
                        if not Path(media_path).is_file():
                            self.logger.debug(
                                f"Cache invalid - missing media file: {media_path}"
                            )
                            return None
                cached_output_dir = cached_data.get("output_dir")
                cached_parsed_dirs = cached_data.get("parsed_output_dirs") or []
                extra_pairs = None
                if cached_output_dir and cached_parsed_dirs:
                    resolved_base = str(Path(cached_output_dir).resolve())
                    extra_pairs = [
                        (resolved_base, str(Path(d).resolve()))
                        for d in cached_parsed_dirs
                    ]
                self._record_parsed_output_location(
                    doc_id,
                    cached_data.get("file_path") or file_path,
                    cached_output_dir,
                    extra_pairs=extra_pairs,
                )
                self.logger.debug(
                    f"Found valid cached parsing result for key: {cache_key}"
                )
                return content_list, doc_id
            else:
                self.logger.debug(
                    f"Cache incomplete - missing content or doc_id: {cache_key}"
                )
                return None

        except Exception as e:
            self.logger.warning(f"Error accessing parse cache: {e}")

        return None

    def _compute_parsed_output_dirs(
        self,
        file_path: str | Path | None,
        output_dir: str | Path | None = None,
    ) -> tuple[Path | None, list[Path]]:
        """Compute the resolved output base and per-document parsed output directories."""
        effective_output_dir = (
            output_dir
            if output_dir is not None
            else getattr(getattr(self, "config", None), "parser_output_dir", None)
        )
        if not effective_output_dir or not file_path:
            return None, []

        file_path_obj = Path(file_path)
        ext = file_path_obj.suffix.lower()
        if ext in AUDIO_FILE_EXTENSIONS or ext in VIDEO_FILE_EXTENSIONS:
            return None, []

        output_base = Path(effective_output_dir).resolve()
        primary_dir = Parser._unique_output_dir(output_base, file_path_obj).resolve()
        dirs = [primary_dir]

        if ext in {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}:
            converted_pdf = primary_dir / f"{file_path_obj.stem}.pdf"
            secondary_dir = Parser._unique_output_dir(
                output_base, converted_pdf
            ).resolve()
            if secondary_dir != primary_dir:
                dirs.append(secondary_dir)

        return output_base, dirs

    def _record_parsed_output_location(
        self,
        doc_id: str | None,
        file_path: str | Path | None,
        output_dir: str | Path | None = None,
        *,
        fallback_doc_id: str | None = None,
        extra_pairs: list[tuple[str, str]] | None = None,
    ) -> dict[str, Any] | None:
        """Record the resolved parsed-output directory locations for a document."""
        if not hasattr(self, "_parsed_output_locations"):
            self._parsed_output_locations: dict[str, dict[str, Any]] = {}

        pairs: list[tuple[str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()

        def _add_pair(base_str: str, dir_str: str) -> None:
            if not base_str or not dir_str:
                return
            base_resolved = str(Path(base_str).resolve())
            dir_resolved = str(Path(dir_str).resolve())
            key = (base_resolved, dir_resolved)
            if key not in seen_pairs:
                seen_pairs.add(key)
                pairs.append(key)

        if (
            fallback_doc_id is not None
            and fallback_doc_id in self._parsed_output_locations
        ):
            prev = self._parsed_output_locations[fallback_doc_id]
            for base_str, dir_str in prev.get("pairs", []):
                _add_pair(base_str, dir_str)

        if doc_id is not None and doc_id in self._parsed_output_locations:
            prev = self._parsed_output_locations[doc_id]
            for base_str, dir_str in prev.get("pairs", []):
                _add_pair(base_str, dir_str)

        if extra_pairs:
            for base_str, dir_str in extra_pairs:
                _add_pair(base_str, dir_str)

        output_base, computed_dirs = self._compute_parsed_output_dirs(
            file_path, output_dir
        )
        if output_base is not None:
            for d in computed_dirs:
                _add_pair(str(output_base), str(d))

        if not pairs:
            return None

        resolved_source = str(Path(file_path).resolve()) if file_path else ""
        record = {
            "source_file_path": resolved_source,
            "output_base": (
                str(output_base) if output_base is not None else pairs[-1][0]
            ),
            "parsed_output_dirs": [d for _, d in pairs],
            "pairs": pairs,
        }

        if doc_id is not None:
            self._parsed_output_locations[doc_id] = record
        if fallback_doc_id is not None and fallback_doc_id != doc_id:
            self._parsed_output_locations.setdefault(fallback_doc_id, record)

        return record

    async def _store_cached_result(
        self,
        cache_key: str,
        content_list: list[dict[str, Any]],
        doc_id: str,
        file_path: Path,
        parse_method: str = None,
        **kwargs,
    ) -> None:
        """
        Store parsing result in cache

        Args:
            cache_key: Cache key to store under
            content_list: Content list to cache
            doc_id: Content-based document ID
            file_path: Path to the file for mtime storage
            parse_method: Parse method used
            **kwargs: Additional parser parameters
        """
        output_dir = kwargs.pop("output_dir", None)
        if not hasattr(self, "parse_cache") or self.parse_cache is None:
            return

        try:
            file_mtime = file_path.stat().st_mtime

            parse_config = {
                "parser": self.config.parser,
                "parse_method": parse_method or self.config.parse_method,
            }
            if getattr(self.config, "merge_continued_tables", False):
                parse_config["merge_continued_tables"] = True

            parse_config.update(self._relevant_parser_kwargs(kwargs))

            output_base, parsed_dirs = self._compute_parsed_output_dirs(
                file_path, output_dir
            )

            cache_data = {
                cache_key: {
                    "content_list": content_list,
                    "doc_id": doc_id,
                    "mtime": file_mtime,
                    "parse_config": parse_config,
                    "cached_at": time.time(),
                    "cache_version": "1.0",
                    "file_path": str(Path(file_path).resolve()),
                    "output_dir": str(output_base) if output_base is not None else "",
                    "parsed_output_dirs": [str(d) for d in parsed_dirs],
                }
            }
            await self.parse_cache.upsert(cache_data)
            await self.parse_cache.index_done_callback()
            self.logger.info(f"Stored parsing result in cache: {cache_key}")
        except Exception as e:
            self.logger.warning(f"Error storing to parse cache: {e}")

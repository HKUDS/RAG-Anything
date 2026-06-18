import json
import logging
import os
import re
import time
import base64
import hashlib
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union, Iterator


from .base import Parser
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Any, Optional



class PaddleOCRParser(Parser):
    """PaddleOCR document parser with optional PDF page rendering support."""

    def __init__(self, default_lang: str = "en") -> None:
        super().__init__()
        self.default_lang = default_lang
        self._ocr_instances: Dict[str, Any] = {}

    def _require_paddleocr(self):
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise ImportError(
                "PaddleOCR parser requires optional dependency `paddleocr`. "
                "Install with `pip install -e '.[paddleocr]'` or "
                "`uv sync --extra paddleocr`. "
                "PaddleOCR also needs `paddlepaddle`; install it from "
                "https://www.paddlepaddle.org.cn/install/quick."
            ) from exc
        return PaddleOCR

    def _get_ocr(self, lang: Optional[str] = None):
        PaddleOCR = self._require_paddleocr()
        language = (lang or self.default_lang).strip() or self.default_lang
        cached = self._ocr_instances.get(language)
        if cached is not None:
            return cached

        init_candidates = [
            {"lang": language, "show_log": False},
            {"lang": language},
            {},
        ]
        last_exception = None
        for candidate_kwargs in init_candidates:
            try:
                ocr = PaddleOCR(**candidate_kwargs)
                self._ocr_instances[language] = ocr
                return ocr
            except Exception as exc:  # pragma: no cover - defensive fallback
                last_exception = exc
                continue

        raise RuntimeError(
            f"Unable to initialize PaddleOCR for language '{language}': {last_exception}"
        )

    def _extract_text_lines(self, result: Any) -> List[str]:
        lines: List[str] = []

        def append_text(text: str) -> None:
            clean_text = text.strip()
            if clean_text:
                lines.append(clean_text)

        if isinstance(result, str):
            append_text(result)
            return lines

        def visit(node: Any) -> None:
            if node is None:
                return

            if hasattr(node, "to_dict"):
                try:
                    visit(node.to_dict())
                    return
                except Exception:
                    pass

            if isinstance(node, dict):
                rec_texts = node.get("rec_texts")
                if isinstance(rec_texts, list):
                    for item in rec_texts:
                        if isinstance(item, str):
                            append_text(item)
                        else:
                            visit(item)

                text_value = node.get("text")
                if isinstance(text_value, str):
                    append_text(text_value)

                texts_value = node.get("texts")
                if isinstance(texts_value, list):
                    for item in texts_value:
                        if isinstance(item, str):
                            append_text(item)
                        else:
                            visit(item)

                # Avoid double-visiting keys we already handled above; this prevents
                # accidental duplication without content-level deduplication.
                for key, value in node.items():
                    if key in {"rec_texts", "text", "texts"}:
                        continue
                    visit(value)
                return

            if isinstance(node, (list, tuple)):
                if node and all(isinstance(item, str) for item in node):
                    for item in node:
                        append_text(item)
                    return

                if (
                    len(node) >= 2
                    and isinstance(node[1], (list, tuple))
                    and len(node[1]) >= 1
                    and isinstance(node[1][0], str)
                ):
                    append_text(node[1][0])
                    return

                if (
                    len(node) >= 1
                    and isinstance(node[0], str)
                    and (len(node) == 1 or isinstance(node[1], (int, float)))
                ):
                    append_text(node[0])
                    return

                for item in node:
                    visit(item)
                return

            if isinstance(node, str):
                append_text(node)
                return

        visit(result)
        return lines

    def _ocr_input(
        self, input_data: Any, lang: Optional[str] = None, cls_enabled: bool = True
    ) -> List[str]:
        ocr = self._get_ocr(lang=lang)

        if hasattr(ocr, "ocr"):
            try:
                result = ocr.ocr(input_data, cls=cls_enabled)
            except TypeError:
                result = ocr.ocr(input_data)
            return self._extract_text_lines(result)

        if hasattr(ocr, "predict"):
            result = ocr.predict(input_data)
            return self._extract_text_lines(result)

        raise RuntimeError(
            "Unsupported PaddleOCR API: expected `ocr` or `predict` method."
        )

    def _extract_pdf_page_inputs(self, pdf_path: Path) -> Iterator[Tuple[int, Any]]:
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:
            raise ImportError(
                "PDF parsing with parser='paddleocr' requires `pypdfium2`. "
                "Install with `pip install -e '.[paddleocr]'` or "
                "`uv sync --extra paddleocr`."
            ) from exc

        pdf = pdfium.PdfDocument(str(pdf_path))
        try:
            total_pages = len(pdf)
            for page_idx in range(total_pages):
                page = pdf[page_idx]
                try:
                    rendered = page.render(scale=2.0)
                    if hasattr(rendered, "to_pil"):
                        yield (page_idx, rendered.to_pil())
                    elif hasattr(rendered, "to_numpy"):
                        yield (page_idx, rendered.to_numpy())
                    else:
                        raise RuntimeError(
                            "Unsupported rendered page format from pypdfium2."
                        )
                finally:
                    if hasattr(page, "close"):
                        page.close()
        finally:
            if hasattr(pdf, "close"):
                pdf.close()

    def _ocr_rendered_page(
        self, rendered_page: Any, lang: Optional[str] = None, cls_enabled: bool = True
    ) -> List[str]:
        if hasattr(rendered_page, "save"):
            temp_image_path: Optional[Path] = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp:
                    temp_image_path = Path(temp.name)
                rendered_page.save(temp_image_path)
                return self._ocr_input(
                    str(temp_image_path), lang=lang, cls_enabled=cls_enabled
                )
            finally:
                if temp_image_path is not None and temp_image_path.exists():
                    try:
                        temp_image_path.unlink()
                    except Exception:
                        pass

        return self._ocr_input(rendered_page, lang=lang, cls_enabled=cls_enabled)

    def parse_pdf(
        self,
        pdf_path: Union[str, Path],
        output_dir: Optional[str] = None,
        method: str = "auto",
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        del output_dir, method
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")

        cls_enabled = kwargs.get("cls", True)
        content_list: List[Dict[str, Any]] = []
        page_inputs = self._extract_pdf_page_inputs(pdf_path)
        try:
            for page_idx, rendered_page in page_inputs:
                page_lines = self._ocr_rendered_page(
                    rendered_page, lang=lang, cls_enabled=cls_enabled
                )
                for text in page_lines:
                    content_list.append(
                        {"type": "text", "text": text, "page_idx": int(page_idx)}
                    )
        finally:
            # Ensure we promptly release PDF handles even if OCR fails mid-stream.
            close = getattr(page_inputs, "close", None)
            if callable(close):
                close()
        return content_list

    def parse_image(
        self,
        image_path: Union[str, Path],
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        del output_dir
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image file does not exist: {image_path}")

        ext = image_path.suffix.lower()
        if ext not in self.IMAGE_FORMATS:
            raise ValueError(
                f"Unsupported image format: {ext}. Supported formats: {', '.join(sorted(self.IMAGE_FORMATS))}"
            )

        cls_enabled = kwargs.get("cls", True)
        page_idx = int(kwargs.get("page_idx", 0))
        text_lines = self._ocr_input(
            str(image_path), lang=lang, cls_enabled=cls_enabled
        )
        return [
            {"type": "text", "text": text, "page_idx": page_idx} for text in text_lines
        ]

    def parse_office_doc(
        self,
        doc_path: Union[str, Path],
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        pdf_path = self.convert_office_to_pdf(doc_path, output_dir)
        return self.parse_pdf(
            pdf_path=pdf_path, output_dir=output_dir, lang=lang, **kwargs
        )

    def parse_text_file(
        self,
        text_path: Union[str, Path],
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        pdf_path = self.convert_text_to_pdf(text_path, output_dir)
        return self.parse_pdf(
            pdf_path=pdf_path, output_dir=output_dir, lang=lang, **kwargs
        )

    def parse_document(
        self,
        file_path: Union[str, Path],
        method: str = "auto",
        output_dir: Optional[str] = None,
        lang: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        del method
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File does not exist: {file_path}")

        ext = file_path.suffix.lower()
        if ext == ".pdf":
            return self.parse_pdf(file_path, output_dir, lang=lang, **kwargs)
        if ext in self.IMAGE_FORMATS:
            return self.parse_image(file_path, output_dir, lang=lang, **kwargs)
        if ext in self.OFFICE_FORMATS:
            return self.parse_office_doc(file_path, output_dir, lang=lang, **kwargs)
        if ext in self.TEXT_FORMATS:
            return self.parse_text_file(file_path, output_dir, lang=lang, **kwargs)

        raise ValueError(
            f"Unsupported file format: {ext}. "
            "PaddleOCR parser supports PDF, image, office, and text formats."
        )

    def check_installation(self) -> bool:
        try:
            self._require_paddleocr()
            return True
        except ImportError:
            return False


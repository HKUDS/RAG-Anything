"""
Local web UI to try RAG-Anything: upload a document, then query the knowledge base.

Run from repo root:
  pip install -e ".[web]"
  uvicorn webapp.main:app --reload --host 0.0.0.0 --port 8765

Configure OpenAI-compatible API via the form or environment variables
(OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL, EMBEDDING_MODEL, EMBEDDING_DIM, etc.).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

load_dotenv(dotenv_path=".env", override=False)

from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc

from raganything import RAGAnything, RAGAnythingConfig


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"


def _abs_workspace_path(path_str: str) -> str:
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = (_repo_root() / p).resolve()
    return str(p)


class ConfigureBody(BaseModel):
    api_key: str = Field(
        default="",
        description=(
            "OpenAI-compatible API key; if empty, OPENAI_API_KEY/LLM_BINDING_API_KEY env is used."
        ),
    )
    base_url: Optional[str] = None
    llm_model: str = Field(
        default_factory=lambda: os.getenv("LLM_MODEL", "qwen2.5-omni-7b")
    )
    vision_model: str = Field(
        default_factory=lambda: os.getenv("VISION_MODEL", "qwen2.5-omni-7b")
    )
    embedding_binding: str = Field(
        default_factory=lambda: os.getenv("EMBEDDING_BINDING", "dashscope_mm")
    )
    dashscope_api_key: str = Field(
        default="",
        description="Optional DashScope API key for embedding_binding=dashscope_mm.",
    )
    embedding_model: str = Field(
        default_factory=lambda: os.getenv(
            "EMBEDDING_MODEL", "tongyi-embedding-vision-flash-2026-03-06"
        )
    )
    embedding_dim: int = Field(
        default_factory=lambda: int(os.getenv("EMBEDDING_DIM", "768"))
    )
    working_dir: str = Field(
        default_factory=lambda: os.getenv("WORKING_DIR", "./rag_storage_web")
    )
    output_dir: str = Field(
        default_factory=lambda: os.getenv("OUTPUT_DIR", "./output_web")
    )
    parser: str = Field(default_factory=lambda: os.getenv("PARSER", "mineru"))
    parse_method: str = Field(default_factory=lambda: os.getenv("PARSE_METHOD", "auto"))


class QueryBody(BaseModel):
    question: str = Field(..., min_length=1)
    mode: str = Field(default="hybrid")
    vlm_enhanced: Optional[bool] = None


class MultimodalQueryBody(BaseModel):
    question: str = Field(..., min_length=1)
    mode: str = Field(default="hybrid")
    content_type: str = Field(..., description="table or equation")
    table_csv: Optional[str] = None
    table_caption: str = ""
    latex: Optional[str] = None
    equation_caption: str = ""


class AppState:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.rag: Optional[RAGAnything] = None
        self.last_init_error: Optional[str] = None
        self.uploads_dir = _repo_root() / "webapp_uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    async def finalize_rag(self) -> None:
        if self.rag is not None:
            try:
                await self.rag.finalize_storages()
            except Exception:
                pass
            self.rag = None


state = AppState()


@asynccontextmanager
async def _lifespan(_: FastAPI):
    yield
    async with state.lock:
        await state.finalize_rag()


def _build_rag_from_config(body: ConfigureBody) -> RAGAnything:
    api_key = (
        (body.api_key or "").strip()
        or (os.getenv("OPENAI_API_KEY") or "").strip()
        or (os.getenv("LLM_BINDING_API_KEY") or "").strip()
    )
    if not api_key:
        raise ValueError(
            "缺少 API Key：请在页面填写，或设置环境变量 OPENAI_API_KEY/LLM_BINDING_API_KEY。"
        )
    base_url = (
        (body.base_url or "").strip()
        or os.getenv("OPENAI_BASE_URL")
        or os.getenv("LLM_BINDING_HOST")
        or None
    )
    if base_url == "":
        base_url = None
    working_dir = _abs_workspace_path(body.working_dir)
    output_dir = _abs_workspace_path(body.output_dir)

    def llm_model_func(
        prompt, system_prompt=None, history_messages=None, **kwargs
    ):
        if history_messages is None:
            history_messages = []
        return openai_complete_if_cache(
            body.llm_model,
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )

    def vision_model_func(
        prompt,
        system_prompt=None,
        history_messages=None,
        image_data=None,
        messages=None,
        **kwargs,
    ):
        if history_messages is None:
            history_messages = []
        if messages:
            return openai_complete_if_cache(
                body.vision_model,
                "",
                system_prompt=None,
                history_messages=[],
                messages=messages,
                api_key=api_key,
                base_url=base_url,
                **kwargs,
            )
        if image_data:
            return openai_complete_if_cache(
                body.vision_model,
                "",
                system_prompt=None,
                history_messages=[],
                messages=[
                    {"role": "system", "content": system_prompt}
                    if system_prompt
                    else None,
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}"
                                },
                            },
                        ],
                    }
                    if image_data
                    else {"role": "user", "content": prompt},
                ],
                api_key=api_key,
                base_url=base_url,
                **kwargs,
            )
        return llm_model_func(prompt, system_prompt, history_messages, **kwargs)

    embedding_binding = (body.embedding_binding or "openai_compatible").strip().lower()

    def _extract_dashscope_vectors(resp: Any) -> np.ndarray:
        status_code = getattr(resp, "status_code", None)
        if status_code is None and isinstance(resp, dict):
            status_code = resp.get("status_code")
        if status_code not in (None, 200):
            msg = getattr(resp, "message", None)
            if not msg and isinstance(resp, dict):
                msg = resp.get("message") or resp.get("code")
            raise RuntimeError(f"DashScope embedding request failed: {msg or status_code}")

        output = getattr(resp, "output", None)
        if output is None and isinstance(resp, dict):
            output = resp.get("output")

        items = None
        if isinstance(output, dict):
            items = output.get("embeddings") or output.get("data")
        elif output is not None:
            items = getattr(output, "embeddings", None) or getattr(output, "data", None)
        if items is None and isinstance(resp, dict):
            items = resp.get("embeddings")

        vectors: list[list[float]] = []
        if items:
            for item in items:
                vec = None
                if isinstance(item, dict):
                    vec = item.get("embedding") or item.get("vector")
                else:
                    vec = getattr(item, "embedding", None) or getattr(item, "vector", None)
                if vec:
                    vectors.append(vec)

        if not vectors:
            raise RuntimeError("DashScope embedding response missing vectors")
        # LightRAG embedding pipeline expects numpy arrays (uses `.size`).
        return np.asarray(vectors, dtype=np.float32)

    if embedding_binding == "dashscope_mm":
        dashscope_api_key = (
            (body.dashscope_api_key or "").strip()
            or (os.getenv("DASHSCOPE_API_KEY") or "").strip()
            or api_key
        )
        if not dashscope_api_key:
            raise ValueError(
                "embedding_binding=dashscope_mm 时需要 DashScope API Key。"
            )
        dashscope_model = (
            (body.embedding_model or "").strip()
            or "tongyi-embedding-vision-flash-2026-03-06"
        )

        async def dashscope_mm_embed(texts: list[str]) -> np.ndarray:
            def _call():
                import dashscope

                dashscope.api_key = dashscope_api_key
                return dashscope.MultiModalEmbedding.call(
                    model=dashscope_model,
                    input=[{"text": t} for t in texts],
                )

            resp = await asyncio.to_thread(_call)
            return _extract_dashscope_vectors(resp)

        embedding_func = EmbeddingFunc(
            embedding_dim=body.embedding_dim,
            max_token_size=8192,
            func=dashscope_mm_embed,
        )
    else:
        embedding_func = EmbeddingFunc(
            embedding_dim=body.embedding_dim,
            max_token_size=8192,
            func=lambda texts: openai_embed.func(
                texts,
                model=body.embedding_model,
                api_key=api_key,
                base_url=base_url,
            ),
        )

    cfg = RAGAnythingConfig(
        working_dir=working_dir,
        parser_output_dir=output_dir,
        parser=body.parser,
        parse_method=body.parse_method,
        enable_image_processing=True,
        enable_table_processing=True,
        enable_equation_processing=True,
    )

    return RAGAnything(
        config=cfg,
        llm_model_func=llm_model_func,
        vision_model_func=vision_model_func,
        embedding_func=embedding_func,
    )


app = FastAPI(
    title="RAG-Anything Web Demo",
    version="0.1.0",
    lifespan=_lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def index_page():
    index = _static_dir() / "index.html"
    if not index.exists():
        raise HTTPException(status_code=500, detail="Missing webapp/static/index.html")
    return FileResponse(index)


@app.get("/api/status")
async def api_status():
    parser_ok: Optional[bool] = None
    if state.rag is not None:
        try:
            parser_ok = state.rag.check_parser_installation()
        except Exception:
            parser_ok = False
    return {
        "initialized": state.rag is not None,
        "parser_ok": parser_ok,
        "last_error": state.last_init_error,
        "working_dir": state.rag.config.working_dir if state.rag else None,
        "env_has_api_key": bool(
            os.getenv("OPENAI_API_KEY", "").strip()
            or os.getenv("LLM_BINDING_API_KEY", "").strip()
            or os.getenv("DASHSCOPE_API_KEY", "").strip()
        ),
    }


@app.post("/api/configure")
async def api_configure(body: ConfigureBody):
    async with state.lock:
        state.last_init_error = None
        await state.finalize_rag()
        rag: Optional[RAGAnything] = None
        try:
            rag = _build_rag_from_config(body)
            result = await rag._ensure_lightrag_initialized()
            if isinstance(result, dict) and not result.get("success", True):
                err = result.get("error", "Initialization failed")
                state.last_init_error = err
                try:
                    await rag.finalize_storages()
                except Exception:
                    pass
                raise HTTPException(status_code=400, detail=err)
            state.rag = rag
            rag = None
        except HTTPException:
            if rag is not None:
                try:
                    await rag.finalize_storages()
                except Exception:
                    pass
            raise
        except Exception as e:
            state.last_init_error = str(e)
            if rag is not None:
                try:
                    await rag.finalize_storages()
                except Exception:
                    pass
            raise HTTPException(status_code=400, detail=str(e)) from e

    parser_ok = state.rag.check_parser_installation() if state.rag else False
    return {"ok": True, "parser_ok": parser_ok}


@app.post("/api/upload")
async def api_upload(
    file: UploadFile = File(...),
    parse_method: Optional[str] = Form(None),
):
    original_name = file.filename or ""
    if not original_name:
        raise HTTPException(status_code=400, detail="Missing filename")

    suffix = Path(original_name).suffix.lower()
    if suffix not in RAGAnythingConfig().supported_file_extensions:
        exts = ", ".join(RAGAnythingConfig().supported_file_extensions)
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported extension '{suffix}'. Allowed: {exts}",
        )

    async with state.lock:
        if state.rag is None:
            raise HTTPException(
                status_code=400,
                detail="请先点击「连接模型」完成配置（或检查服务端环境变量）。",
            )
        safe_name = f"{uuid.uuid4().hex}{suffix}"
        dest = state.uploads_dir / safe_name
        try:
            with dest.open("wb") as out:
                shutil.copyfileobj(file.file, out)
        finally:
            await file.close()

        pm = parse_method or state.rag.config.parse_method
        try:
            await state.rag.process_document_complete(
                file_path=str(dest),
                parse_method=pm,
            )
        except Exception as e:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
            raise HTTPException(status_code=500, detail=str(e)) from e

    return {"ok": True, "stored_as": safe_name, "original_name": original_name}


@app.post("/api/query")
async def api_query(body: QueryBody):
    async with state.lock:
        if state.rag is None:
            raise HTTPException(status_code=400, detail="请先完成「连接模型」配置。")
        kwargs: dict[str, Any] = {}
        if body.vlm_enhanced is not None:
            kwargs["vlm_enhanced"] = body.vlm_enhanced
        try:
            answer = await state.rag.aquery(body.question, mode=body.mode, **kwargs)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
    return {"answer": answer}


@app.post("/api/query_multimodal")
async def api_query_multimodal(body: MultimodalQueryBody):
    if body.content_type not in ("table", "equation"):
        raise HTTPException(
            status_code=400, detail="content_type 必须是 table 或 equation"
        )
    multimodal_content: list[dict[str, Any]]
    if body.content_type == "table":
        if not (body.table_csv or "").strip():
            raise HTTPException(status_code=400, detail="表格查询需要填写 table_csv")
        multimodal_content = [
            {
                "type": "table",
                "table_data": body.table_csv.strip(),
                "table_caption": body.table_caption or None,
            }
        ]
    else:
        if not (body.latex or "").strip():
            raise HTTPException(status_code=400, detail="公式查询需要填写 latex")
        multimodal_content = [
            {
                "type": "equation",
                "latex": body.latex.strip(),
                "equation_caption": body.equation_caption or None,
            }
        ]

    async with state.lock:
        if state.rag is None:
            raise HTTPException(status_code=400, detail="请先完成「连接模型」配置。")
        try:
            answer = await state.rag.aquery_with_multimodal(
                body.question,
                multimodal_content=multimodal_content,
                mode=body.mode,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
    return {"answer": answer}


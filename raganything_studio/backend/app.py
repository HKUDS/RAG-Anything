from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from raganything_studio.backend.api import documents, graph, health, jobs, query, settings
from raganything_studio.backend.dependencies import settings as studio_settings


def create_app() -> FastAPI:
    app = FastAPI(title="RAG-Anything Studio")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api/health", tags=["health"])
    app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
    app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
    app.include_router(query.router, prefix="/api/query", tags=["query"])
    app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
    app.include_router(graph.router, prefix="/api/graph", tags=["graph"])

    static_dir = studio_settings.static_dir
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str) -> FileResponse:
        requested = (static_dir / full_path).resolve()
        if _is_static_child(requested, static_dir) and requested.is_file():
            return FileResponse(requested)

        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)

        fallback = static_dir / "studio-placeholder.html"
        return FileResponse(fallback)

    return app


def _is_static_child(path: Path, static_dir: Path) -> bool:
    try:
        path.relative_to(static_dir.resolve())
        return True
    except ValueError:
        return False


app = create_app()


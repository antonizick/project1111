"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from p11 import __version__
from p11.engine.base import Engine

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(web_dir: Path | None = None, engine: Engine | None = None) -> FastAPI:
    app = FastAPI(title="P11 Studio", version=__version__, docs_url=None, redoc_url=None)
    # The engine the API drives (Phase 07 wires the routes and lifecycle).
    app.state.engine = engine

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    static = web_dir or WEB_DIR
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="web")
    return app

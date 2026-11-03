"""FastAPI application factory: the Studio API behind ``SecurityMiddleware`` (spec S1, S2)."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from p11 import __version__
from p11.config import Settings, load_settings
from p11.engine import create_engine
from p11.engine.base import Engine, EngineError
from p11.gpu.telemetry import GpuSampler, default_sampler
from p11.gpulock import GpuLockTimeout
from p11.jobs.errors import problem_for
from p11.jobs.queue import QueueFull
from p11.media.inputs import UnknownInput
from p11.media.validate import UploadRejected
from p11.models.registry import ModelManager
from p11.recipe.compile import CompileError
from p11.recipe.migrate import RecipeFormatError, RecipeVersionError
from p11.recipe.registry import PROVISIONAL_DEFAULT_SET, ModelRegistry, UnknownModelError
from p11.templates.store import TemplateError

from .routes import ROUTERS
from .security import SecurityMiddleware, Session
from .studio import Studio, StudioPaths

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
log = logging.getLogger("p11.api")

#: FastAPI's native OpenTelemetry hooks, all off: P11 sends no telemetry anywhere (S1).
NO_TELEMETRY = {
    "tracing": False,
    "metrics": False,
    "logs": False,
    "operation_spans": False,
    "auto_configure": False,
}
TYPED_ERRORS: tuple[type[Exception], ...] = (
    CompileError,
    RecipeFormatError,
    RecipeVersionError,
    ValidationError,
    UploadRejected,
    UnknownInput,
    TemplateError,
    UnknownModelError,
    EngineError,
    GpuLockTimeout,
)


class AccessLog:
    """One INFO line per request: method, path (never the query string), status, duration."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.monotonic()
        status = 0

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            log.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "ms": round((time.monotonic() - started) * 1000, 1),
                },
            )


def _problem(status: int, code: str, message: str, hint: str = "") -> JSONResponse:
    return JSONResponse({"code": code, "message": message, "hint": hint}, status_code=status)


def _install_handlers(app: FastAPI) -> None:
    async def typed(_: Request, exc: Exception) -> JSONResponse:
        status, err = problem_for(exc)
        return _problem(status, err.code, err.message, err.hint)

    for cls in TYPED_ERRORS:
        app.add_exception_handler(cls, typed)

    async def http_error(_: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, HTTPException)
        return _problem(exc.status_code, f"http.{exc.status_code}", str(exc.detail))

    async def invalid(_: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        msg = f"Invalid request: {first.get('msg', 'bad input')}" + (f" ({where})" if where else "")
        return _problem(422, "request.invalid", msg, "Check the values sent.")

    async def full(_: Request, exc: Exception) -> JSONResponse:
        return _problem(429, "queue.full", str(exc), "Wait for some jobs to finish.")

    async def bad_value(_: Request, exc: Exception) -> JSONResponse:
        return _problem(422, "request.invalid", str(exc), "")

    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(RequestValidationError, invalid)
    app.add_exception_handler(QueueFull, full)
    app.add_exception_handler(ValueError, bad_value)


def create_app(
    web_dir: Path | None = None,
    engine: Engine | None = None,
    *,
    settings: Settings | None = None,
    session: Session | None = None,
    port: int | None = None,
    fake: bool | None = None,
    studio_paths: StudioPaths | None = None,
    sampler: GpuSampler | Literal["auto"] | None = "auto",
    seed_demo: bool = False,
) -> FastAPI:
    """The Studio app. ``engine`` defaults to the pinned ComfyUI (``fake=True``: FakeEngine)."""
    settings = settings or load_settings()
    port = port or settings.studio_port
    if engine is None:
        engine = create_engine(settings, fake=bool(fake))
    if fake is None:
        from p11.engine.fake import FakeEngine

        fake = isinstance(engine, FakeEngine)
    registry: Callable[[], ModelRegistry]
    if fake:
        registry = lambda: PROVISIONAL_DEFAULT_SET  # noqa: E731
    else:
        registry = lambda: ModelManager(settings.models_root).registry()  # noqa: E731
    if sampler == "auto":
        sampler = None if fake else default_sampler()
    studio = Studio(
        settings=settings,
        engine=engine,
        session=session or Session(),
        registry=registry,
        paths=studio_paths or StudioPaths.real(settings),
        port=port,
        fake=fake,
        sampler=sampler,
        idle_stop=settings.engine_idle_stop,
        seed_demo=seed_demo,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await studio.open()
        try:
            yield
        finally:
            await studio.close()

    app = FastAPI(
        title="P11 Studio",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",  # behind the token, like the rest of /api
        lifespan=lifespan,
        telemetry=NO_TELEMETRY,  # type: ignore[arg-type]
    )
    app.state.engine = engine
    app.state.studio = studio
    _install_handlers(app)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    for router in ROUTERS:
        app.include_router(router)

    static_dir = web_dir or WEB_DIR
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    app.add_middleware(SecurityMiddleware, session=studio.session, port=port)
    app.add_middleware(AccessLog)
    return app

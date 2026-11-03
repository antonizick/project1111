"""Builders for Studio API tests: an app on the FakeEngine in throw-away directories."""

from __future__ import annotations

import io
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image

from p11.api.app import create_app
from p11.api.security import Session
from p11.api.studio import Studio, StudioPaths
from p11.config import load_settings
from p11.engine.fake import FakeConfig, FakeEngine
from p11.gpu.telemetry import GpuSampler

PORT = 8111
BASE = f"http://127.0.0.1:{PORT}"


class Client(TestClient):
    """A TestClient that sends the session token unless told not to."""

    session: Session
    studio: Studio
    engine: FakeEngine

    @property
    def auth(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.session.token}"}

    def wait_job(self, job_id: str, timeout: float = 20.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.get(f"/api/jobs/{job_id}", headers=self.auth).json()
            if job["state"] in ("done", "failed", "cancelled"):
                return dict(job)
            time.sleep(0.02)
        raise AssertionError(f"job {job_id} did not finish: {job}")


@contextmanager
def studio_client(
    root: Path,
    *,
    engine: FakeEngine | None = None,
    sampler: GpuSampler | None = None,
    seed_demo: bool = False,
    web_dir: Path | None = None,
    **settings: Any,
) -> Iterator[Client]:
    session = Session()
    engine = engine or FakeEngine(FakeConfig())
    app = create_app(
        web_dir=web_dir or root / "no-web",
        engine=engine,
        settings=load_settings(outputs_root=root / "pictures", **settings),
        session=session,
        port=PORT,
        studio_paths=StudioPaths.sandbox(root),
        sampler=sampler,
        seed_demo=seed_demo,
    )
    with Client(app, base_url=BASE) as client:
        client.session = session
        client.studio = app.state.studio
        client.engine = engine
        yield client


def png_bytes(size: tuple[int, int] = (64, 48), color: str = "teal", **save: Any) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=save.pop("format", "PNG"), **save)
    return buf.getvalue()


def generate_recipe(prompt: str = "a lighthouse on a rocky coast", **fields: Any) -> dict[str, Any]:
    from tests.helpers import recipe

    from p11.recipe.model import Generate

    steps = fields.pop("steps", None) or (Generate(prompt=prompt, aspect="1:1-1024"),)
    return recipe(*steps, **fields).model_dump(mode="json")


Poll = Callable[[], bool]


def eventually(check: Poll, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached in time")

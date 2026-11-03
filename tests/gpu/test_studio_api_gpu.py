"""Acceptance (Phase 07): a wallpaper job through the Studio API on the real engine.

``POST /api/jobs`` with the default wallpaper preset runs on ``ComfyEngine`` (the installed engine,
the real models directory and the real GPU lock, R24), and the result is in ``GET /api/gallery``
with its recipe embedded in the PNG. Outputs and the index go to a temp dir; the engine is
stopped by the app's shutdown, so no engine process is left behind.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.helpers import recipe

from p11.api.app import create_app
from p11.api.security import Session
from p11.api.studio import StudioPaths
from p11.config import load_settings
from p11.engine.comfy import ComfyEngine, EngineConfig
from p11.engine.process import pid_alive
from p11.outputs import metadata
from p11.recipe.model import Generate

DATA = Path.home() / ".local/share/p11"


@pytest.mark.gpu
def test_wallpaper_job_through_the_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not (DATA / "engine/venv/bin/python").exists():
        pytest.skip("engine not installed (scripts/engine_setup.sh)")
    for var in ("P11_CONFIG_DIR", "P11_DATA_DIR", "P11_CACHE_DIR", "P11_PICTURES_DIR"):
        monkeypatch.delenv(var, raising=False)
    settings = load_settings(models_root=DATA / "models", outputs_root=tmp_path / "pictures")
    engine = ComfyEngine(EngineConfig.default(settings, lock_timeout=1800))
    session = Session()
    app = create_app(
        web_dir=tmp_path / "none",
        engine=engine,
        settings=settings,
        session=session,
        port=8111,
        studio_paths=StudioPaths.sandbox(tmp_path),
        sampler=None,
    )
    auth = {"authorization": f"Bearer {session.token}"}
    body = recipe(
        Generate(prompt="a lighthouse on a rocky coast at dusk", aspect="16:9-1920x1080")
    ).model_dump(mode="json")
    with TestClient(app, base_url="http://127.0.0.1:8111") as c:
        job = c.post("/api/jobs", headers=auth, json={"recipe": body}).json()
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            job = c.get(f"/api/jobs/{job['id']}", headers=auth).json()
            if job["state"] in ("done", "failed", "cancelled"):
                break
            time.sleep(0.5)
        assert job["state"] == "done", job
        page = c.get("/api/gallery", headers=auth).json()
        assert page["total"] == 1
        item = page["items"][0]
        assert (item["width"], item["height"]) == (1920, 1080)
        path = tmp_path / "pictures" / item["path"]
        assert metadata.read_recipe_from_png(path).model_dump(mode="json") == body
        run = c.get(f"/api/images/{item['id']}/recipe", headers=auth).json()
        assert run["engine_version"] == "0.43.0" and run["timings"]["total"] > 0
        assert set(run["model_hashes"]) >= {"realvisxl5-lightning", "sdxl-vae-fp16-fix"}
        pid = (c.get("/api/system", headers=auth).json()["engine"])["pid"]
    assert pid and not pid_alive(pid)

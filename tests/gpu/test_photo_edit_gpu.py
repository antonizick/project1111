"""Acceptance (Phase 17b): photo edit (img2img) on the real engine with every strength preset.

A P11-generated 1920x1080 picture (synthetic prompt, no real people, S6) is uploaded as a new
photo; each preset runs through the Studio API on ``ComfyEngine`` (real models, GPU lock R24)
without OOM, at the size the compiler computed (bucket 1344x768, then the model chain toward
1920x1080), and changes the picture more as the strength rises. A template saved from a photo edit
has a ``start_photo`` slot and re-runs. The engine stops with the app.
"""

from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops, ImageStat
from tests.helpers import recipe

from p11.api.app import create_app
from p11.api.security import Session
from p11.api.studio import StudioPaths
from p11.config import load_settings
from p11.engine.comfy import ComfyEngine, EngineConfig
from p11.engine.process import pid_alive
from p11.recipe.compile import nearest_bucket, photo_output
from p11.recipe.model import FileRef, FixedSeed, Generate

DATA = Path.home() / ".local/share/p11"
SIZE = (1920, 1080)


def _wait(c: TestClient, auth: dict[str, str], job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        job = c.get(f"/api/jobs/{job_id}", headers=auth).json()
        if job["state"] in ("done", "failed", "cancelled"):
            return dict(job)
        time.sleep(0.5)
    raise AssertionError("job did not finish")


def _image(c: TestClient, auth: dict[str, str], image_id: int) -> Image.Image:
    data = c.get(f"/api/images/{image_id}", headers=auth).content
    return Image.open(io.BytesIO(data)).convert("RGB")


@pytest.mark.gpu
def test_photo_edit_presets_on_the_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not (DATA / "engine/venv/bin/python").exists():
        pytest.skip("engine not installed (scripts/engine_setup.sh)")
    for var in ("P11_CONFIG_DIR", "P11_DATA_DIR", "P11_CACHE_DIR", "P11_PICTURES_DIR"):
        monkeypatch.delenv(var, raising=False)
    settings = load_settings(models_root=DATA / "models", outputs_root=tmp_path / "pictures")
    engine = ComfyEngine(EngineConfig.default(settings, lock_timeout=1800))
    session = Session()
    app = create_app(
        web_dir=tmp_path / "none", engine=engine, settings=settings, session=session,
        port=8111, studio_paths=StudioPaths.sandbox(tmp_path), sampler=None,
    )  # fmt: skip
    auth = {"authorization": f"Bearer {session.token}"}
    expected = photo_output(nearest_bucket("sdxl", *SIZE), *SIZE)

    with TestClient(app, base_url="http://127.0.0.1:8111") as c:
        gen = recipe(
            Generate(prompt="a white suburban house with a driveway", aspect="16:9-1920x1080")
        ).model_dump(mode="json")
        src_job = _wait(
            c, auth, c.post("/api/jobs", headers=auth, json={"recipe": gen}).json()["id"]
        )
        assert src_job["state"] == "done", src_job
        original = _image(c, auth, src_job["images"][0])
        buf = io.BytesIO()
        original.save(buf, format="PNG")
        up = c.post("/api/uploads?kind=image", headers=auth, content=buf.getvalue()).json()

        change: dict[str, float] = {}
        last_id = 0
        for preset in ("light", "change", "reimagine"):
            r = recipe(
                Generate(prompt="the same house painted green", denoise_preset=preset),
                source_image=FileRef(ref=up["id"]),
                seed=FixedSeed(value=77),
                id=f"photo-{preset}",
            ).model_dump(mode="json")
            job = _wait(c, auth, c.post("/api/jobs", headers=auth, json={"recipe": r}).json()["id"])
            assert job["state"] == "done", (preset, job)
            (last_id,) = job["images"]
            out = _image(c, auth, last_id)
            assert out.size == expected, preset
            diff = ImageChops.difference(out.resize(SIZE), original).convert("L")
            change[preset] = ImageStat.Stat(diff).mean[0]
        assert change["light"] < change["change"] < change["reimagine"], change

        t = c.post("/api/templates/from-image", headers=auth,
                   json={"image_id": last_id, "name": "Paint it"})  # fmt: skip
        assert t.status_code == 201, t.text
        tpl = t.json()["recipe"]
        assert [s["name"] for s in tpl["slots"]] == ["start_photo"]
        rerun = c.post("/api/jobs", headers=auth, json={
            "recipe": tpl, "bindings": {"start_photo": {"ref": up["id"]}}})  # fmt: skip
        job = _wait(c, auth, rerun.json()["id"])
        assert job["state"] == "done", job
        pid = c.get("/api/system", headers=auth).json()["engine"]["pid"]
    assert pid and not pid_alive(pid)

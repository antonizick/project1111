"""Acceptance (Phase 10): inpaint a 1920x1080 result on the real engine with every preset.

Each preset runs through the Studio API on ``ComfyEngine`` (real models, GPU lock R24) without OOM;
pixels outside the soft mask's blend band are byte-identical to the original; the result is a child
of the original in the gallery; a template saved from the inpaint (mask kept) re-runs end to end.
The engine stops with the app, so no engine process is left behind.
"""

from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops, ImageDraw
from tests.helpers import recipe

from p11.api.app import create_app
from p11.api.security import Session
from p11.api.studio import StudioPaths
from p11.config import load_settings
from p11.engine.comfy import ComfyEngine, EngineConfig
from p11.engine.process import pid_alive
from p11.media.inpaint import soft_mask
from p11.recipe.model import FileRef, FixedSeed, Generate, Inpaint, Slot

DATA = Path.home() / ".local/share/p11"
SIZE = (1920, 1080)
BOX = (760, 300, 1160, 700)


def _wait(c: TestClient, auth: dict[str, str], job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        job = c.get(f"/api/jobs/{job_id}", headers=auth).json()
        if job["state"] in ("done", "failed", "cancelled"):
            return dict(job)
        time.sleep(0.5)
    raise AssertionError("job did not finish")


def _image(c: TestClient, auth: dict[str, str], image_id: int) -> Image.Image:
    return Image.open(io.BytesIO(c.get(f"/api/images/{image_id}", headers=auth).content)).convert(
        "RGB"
    )


@pytest.mark.gpu
def test_inpaint_presets_on_the_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    painted = Image.new("L", SIZE, 0)
    ImageDraw.Draw(painted).ellipse(BOX, fill=255)
    buf = io.BytesIO()
    painted.save(buf, format="PNG")

    with TestClient(app, base_url="http://127.0.0.1:8111") as c:
        gen = recipe(
            Generate(prompt="portrait of a hiker on a mountain trail", aspect="16:9-1920x1080")
        ).model_dump(mode="json")
        source_job = _wait(
            c, auth, c.post("/api/jobs", headers=auth, json={"recipe": gen}).json()["id"]
        )
        assert source_job["state"] == "done", source_job
        (source_id,) = source_job["images"]
        original = _image(c, auth, source_id)
        assert original.size == SIZE
        mask_id = c.post("/api/uploads?kind=mask", headers=auth, content=buf.getvalue()).json()[
            "id"
        ]

        children = []
        for preset in ("subtle", "balanced", "major"):
            step = Inpaint(mask_slot="mask", prompt="a red wool scarf", denoise_preset=preset)
            r = recipe(step, slots=(Slot(name="mask", kind="mask"),),
                       source_image=FileRef(ref=f"gallery/{source_id}"),
                       seed=FixedSeed(value=42), id=f"inpaint-{preset}")  # fmt: skip
            body = {"recipe": r.model_dump(mode="json"), "bindings": {"mask": {"ref": mask_id}},
                    "parent": source_id}  # fmt: skip
            job = _wait(c, auth, c.post("/api/jobs", headers=auth, json=body).json()["id"])
            assert job["state"] == "done", job
            (child_id,) = job["images"]
            info = c.get(f"/api/images/{child_id}/info", headers=auth).json()
            assert info["parent_id"] == source_id and (info["width"], info["height"]) == SIZE
            out = _image(c, auth, child_id)
            soft = soft_mask(painted, SIZE, step.grow_mask_px, step.mask_blur_px)
            outside = soft.point(lambda v: 255 if v == 0 else 0)
            diff = ImageChops.difference(out, original).convert("L")
            assert ImageChops.multiply(diff, outside).getbbox() is None, preset
            changed = diff.crop(BOX).point(lambda v: 255 if v > 20 else 0).getbbox()
            assert changed is not None, f"{preset}: the masked area did not change"
            children.append(child_id)

        t = c.post("/api/templates/from-image", headers=auth,
                   json={"image_id": children[1], "name": "Scarf", "mask": "fixed"})  # fmt: skip
        assert t.status_code == 201, t.text
        tpl = t.json()["recipe"]
        assert [s["name"] for s in tpl["slots"]] == ["source"]
        rerun = c.post("/api/jobs", headers=auth, json={
            "recipe": tpl, "bindings": {"source": {"ref": f"gallery/{source_id}"}},
            "template": "scarf"})  # fmt: skip
        job = _wait(c, auth, rerun.json()["id"])
        assert job["state"] == "done", job
        assert _image(c, auth, job["images"][0]).size == SIZE
        pid = c.get("/api/system", headers=auth).json()["engine"]["pid"]
    assert pid and not pid_alive(pid)

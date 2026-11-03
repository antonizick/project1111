"""Acceptance (Phase 11): background replacement on the real engine and the real segmenter.

A synthetic product fixture with an exact mask (drawn in code; synthetic only, S6) checks the
segmenter's mask quality against a recorded IoU threshold. A P11-generated subject then gets a
photo background through the Studio API in one job (auto-mask, colour match, harmonize light -
the UI's defaults) without OOM, and a template saved from it (subject re-segmented each run)
re-runs on a new subject image. The engine stops with the app, so no engine process is left
behind. The ``birefnet-lite`` model must be installed (``p11 models install birefnet-lite``).
"""

from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFilter
from tests.helpers import recipe

from p11.api.app import create_app
from p11.api.security import Session
from p11.api.studio import StudioPaths
from p11.config import load_settings
from p11.engine.comfy import ComfyEngine, EngineConfig
from p11.engine.process import pid_alive
from p11.media.segment import Segmenters
from p11.models.registry import ModelManager
from p11.recipe.model import FileRef, FixedSeed, Generate, ReplaceBackground, Slot

DATA = Path.home() / ".local/share/p11"
SIZE = (1024, 1024)
#: Measured on the laptop with ``birefnet-lite``: IoU 0.979 on this fixture (2026-11-03; see
#: docs/P11_BENCHMARKS.md -> Background replacement). The threshold leaves room for runtime drift.
IOU_MIN = 0.85


def synthetic_scene(size: tuple[int, int] = (768, 768)) -> tuple[bytes, Image.Image]:
    """A synthetic product ("bottle") on a soft two-tone scene, and its exact mask."""
    w, h = size
    bg = Image.new("RGB", size, (70, 90, 120))
    d = ImageDraw.Draw(bg)
    for i in range(0, h, 24):
        d.rectangle((0, i, w, i + 24), fill=(60 + i // 8, 80 + i // 10, 110 + i // 12))
    for cx, cy, r in ((120, 120, 90), (640, 200, 120), (500, 620, 110)):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(95, 115, 145))
    bg = bg.filter(ImageFilter.GaussianBlur(18))
    gt = Image.new("L", size, 0)
    gd = ImageDraw.Draw(gt)
    body = (w // 2 - 110, h // 2 - 180, w // 2 + 110, h // 2 + 220)
    neck = (w // 2 - 45, h // 2 - 280, w // 2 + 45, h // 2 - 160)
    cap = (w // 2 - 55, h // 2 - 330, w // 2 + 55, h // 2 - 275)
    gd.rounded_rectangle(body, radius=60, fill=255)
    gd.rounded_rectangle(neck, radius=20, fill=255)
    gd.rectangle(cap, fill=255)
    out = bg.copy()
    od = ImageDraw.Draw(out)
    od.rounded_rectangle(body, radius=60, fill=(150, 40, 45))
    od.rounded_rectangle(neck, radius=20, fill=(160, 50, 55))
    od.rectangle(cap, fill=(30, 30, 35))
    od.rectangle((w // 2 - 78, h // 2 - 150, w // 2 - 50, h // 2 + 160), fill=(185, 85, 85))
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue(), gt


def synthetic_photo(size: tuple[int, int] = (1280, 720)) -> bytes:
    """A photo-like background scene (gradient + bokeh), synthetic (S6)."""
    w, h = size
    img = Image.new("RGB", size, (210, 180, 140))
    d = ImageDraw.Draw(img)
    for i in range(0, h, 16):
        d.rectangle((0, i, w, i + 16), fill=(120 + i // 4, 150 + i // 6, 200 - i // 8))
    for cx, cy, r in ((200, 200, 140), (900, 300, 180), (600, 600, 160), (1150, 150, 120)):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(180, 200, 230))
    img = img.filter(ImageFilter.GaussianBlur(30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _segments() -> Segmenters:
    manager = ModelManager(DATA / "models")

    def resolve(mid: str) -> Path:
        entry = manager.manifest.get(mid)
        if entry is None:
            raise KeyError(mid)
        return manager.path_of(entry)

    return Segmenters(resolve)


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
def test_segmenter_finds_the_synthetic_subject() -> None:
    data, gt = synthetic_scene()
    mask = Image.open(io.BytesIO(_segments().segmenter("birefnet-lite").mask(data))).convert("L")
    found = np.asarray(mask, bool)
    truth = np.asarray(gt, bool)
    iou = float((found & truth).sum() / (found | truth).sum())
    print(f"[segmentation] IoU vs synthetic ground truth: {iou:.3f}")
    assert iou >= IOU_MIN


@pytest.mark.gpu
def test_replace_background_end_to_end_and_template_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not (DATA / "engine/venv/bin/python").exists():
        pytest.skip("engine not installed (scripts/engine_setup.sh)")
    if not (DATA / "models/segmentation/birefnet-lite.onnx").exists():
        pytest.skip("segmentation model not installed (p11 models install birefnet-lite)")
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

    with TestClient(app, base_url="http://127.0.0.1:8111") as c:
        bg_id = c.post("/api/uploads?kind=image", headers=auth, content=synthetic_photo()).json()[
            "id"
        ]

        def subject(prompt: str, seed: int) -> int:
            r = recipe(
                Generate(prompt=prompt, aspect="1:1-1024"), seed=FixedSeed(value=seed)
            ).model_dump(mode="json")
            job = _wait(c, auth, c.post("/api/jobs", headers=auth, json={"recipe": r}).json()["id"])
            assert job["state"] == "done", job
            return int(job["images"][0])

        first = subject("product photo of a red ceramic mug on a wooden table", 2100)
        assert _image(c, auth, first).size == SIZE

        # One Apply on the defaults: auto-mask, colour match on, harmonize light.
        step = ReplaceBackground(
            background_slot="bg", colour_match=True, feather_px=8, relight=True,
            relight_denoise=0.25,
        )  # fmt: skip
        r = recipe(
            step,
            slots=(Slot(name="bg", kind="background_image"),),
            source_image=FileRef(ref=f"gallery/{first}"),
            seed=FixedSeed(value=77),
        )
        t0 = time.monotonic()
        job = _wait(
            c,
            auth,
            c.post(
                "/api/jobs",
                headers=auth,
                json={
                    "recipe": r.model_dump(mode="json"),
                    "bindings": {"bg": {"ref": bg_id}},
                    "parent": first,
                },
            ).json()["id"],
        )
        wall = time.monotonic() - t0
        assert job["state"] == "done", job
        (child,) = job["images"]
        info = c.get(f"/api/images/{child}/info", headers=auth).json()
        assert info["parent_id"] == first and (info["width"], info["height"]) == SIZE
        timings = c.get(f"/api/images/{child}/recipe", headers=auth).json()["timings"]
        print(f"[background] one Apply on defaults: {wall:.1f} s wall, timings {timings}")

        # A template from it re-segments each run's subject and re-runs on a new subject.
        t = c.post("/api/templates/from-image", headers=auth,
                   json={"image_id": child, "name": "On my scene", "mask": "auto"})  # fmt: skip
        assert t.status_code == 201, t.text
        tpl = t.json()["recipe"]
        assert [s["name"] for s in tpl["slots"]] == ["bg", "source"]
        second = subject("portrait of a woman with short dark hair, studio photo", 2101)
        rerun = c.post("/api/jobs", headers=auth, json={
            "recipe": tpl,
            "bindings": {"source": {"ref": f"gallery/{second}"}, "bg": {"ref": bg_id}},
            "template": "on-my-scene"})  # fmt: skip
        job = _wait(c, auth, rerun.json()["id"])
        assert job["state"] == "done", job
        assert _image(c, auth, job["images"][0]).size == SIZE
        pid = c.get("/api/system", headers=auth).json()["engine"]["pid"]
    assert pid and not pid_alive(pid)

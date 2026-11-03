"""Background replacement through the job runner and the Studio API (Phase 11, ADR-0027).

The segmenter is the deterministic stub everywhere here: these tests cover the local-step driver,
the harmonize tail's engine pass, the save/chain rules and the two ``/api/background`` calls. The
real model runs in ``tests/gpu/`` and the acceptance run.
"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image, ImageDraw
from tests.helpers import recipe
from tests.studio import png_bytes, studio_client

from p11.engine.fake import FakeEngine
from p11.jobs.runner import JobControl, Runner
from p11.media.inpaint import MaskError
from p11.media.inputs import InputStore
from p11.media.segment import Segmenters
from p11.outputs.index import GalleryIndex
from p11.recipe.model import FileRef, ReplaceBackground, Slot
from p11.recipe.registry import PROVISIONAL_DEFAULT_SET

BG_SLOT = (Slot(name="bg", kind="background_image"),)


def mask_png(size: tuple[int, int], box: tuple[int, int, int, int] | None) -> bytes:
    img = Image.new("L", size, 0)
    if box is not None:
        ImageDraw.Draw(img).rectangle(box, fill=255)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def test_local_only_step_never_runs_the_engine(tmp_path):
    gallery = GalleryIndex(tmp_path / "g.db")
    inputs = InputStore(tmp_path / "in")
    item = inputs.add_image(png_bytes((16, 16)), "image")
    engine = FakeEngine()
    runner = Runner(
        engine,
        lambda: PROVISIONAL_DEFAULT_SET,
        tmp_path / "out",
        gallery,
        inputs,
        segmenters=Segmenters(stub=True),
    )
    r = recipe(
        ReplaceBackground(background_colour="#336699"),
        source_image=FileRef(ref=item.id),
        id="bg-local",
    )
    report = await runner.run(
        recipe=r,
        bindings={},
        count=1,
        template=None,
        parent=None,
        control=JobControl(),
        publish=lambda *a: None,
        job_id="j1",
        on_progress=lambda f, n: None,
    )
    assert engine.runs == []  # segmentation and compositing stayed in P11
    assert len(report.image_ids) == 1
    entry = gallery.get(report.image_ids[0])
    assert entry is not None and entry.width == 16 and entry.height == 16


async def test_relight_runs_one_engine_pass_and_saves_one_output(tmp_path):
    inputs_root = tmp_path
    gallery = GalleryIndex(inputs_root / "g.db")
    inputs = InputStore(inputs_root / "in")
    subject = inputs.add_image(png_bytes((24, 24)), "image")
    bg = inputs.add_image(png_bytes((24, 24), "red"), "image")
    engine = FakeEngine()
    runner = Runner(
        engine,
        lambda: PROVISIONAL_DEFAULT_SET,
        inputs_root / "out",
        gallery,
        inputs,
        segmenters=Segmenters(stub=True),
    )
    r = recipe(
        ReplaceBackground(background_slot="bg", relight=True),
        slots=BG_SLOT,
        source_image=FileRef(ref=subject.id),
        id="bg-relight",
    )
    await engine.start()
    report = await runner.run(
        recipe=r,
        bindings={"bg": FileRef(ref=bg.id)},
        count=1,
        template=None,
        parent=None,
        control=JobControl(),
        publish=lambda *a: None,
        job_id="j2",
        on_progress=lambda f, n: None,
    )
    await engine.stop()
    # Local composite (no engine) + one harmonize pass on the engine.
    assert len(engine.runs) == 1
    # The composite is intermediate: only the harmonized result is saved.
    assert len(report.image_ids) == 1


async def test_empty_manual_mask_is_refused_before_queueing(tmp_path):
    gallery = GalleryIndex(tmp_path / "g.db")
    inputs = InputStore(tmp_path / "in")
    subject = inputs.add_image(png_bytes((16, 16)), "image")
    runner = Runner(
        FakeEngine(),
        lambda: PROVISIONAL_DEFAULT_SET,
        tmp_path / "out",
        gallery,
        inputs,
        segmenters=Segmenters(stub=True),
    )
    r = recipe(
        ReplaceBackground(
            background_colour="#336699",
            mask_mode="manual",
            mask_png=base64.b64encode(mask_png((8, 8), None)).decode(),
        ),
        source_image=FileRef(ref=subject.id),
        id="bg-empty",
    )
    with pytest.raises(MaskError):
        runner.validate(r, {})


# -- the Studio API ----------------------------------------------------------------------------


def test_mask_and_preview_endpoints_and_a_job(tmp_path):
    with studio_client(tmp_path) as client:
        up = client.post(
            "/api/uploads?kind=image", content=png_bytes((32, 24)), headers=client.auth
        )
        assert up.status_code == 201
        subject_id = up.json()["id"]

        m = client.post(
            "/api/background/mask",
            json={"image": {"ref": subject_id}},
            headers=client.auth,
        )
        assert m.status_code == 200 and m.headers["content-type"] == "image/png"
        assert Image.open(io.BytesIO(m.content)).size == (32, 24)

        bg_upload = client.post(
            "/api/uploads?kind=image", content=png_bytes((32, 24), "red"), headers=client.auth
        )
        p = client.post(
            "/api/background/preview",
            json={
                "image": {"ref": subject_id},
                "background": {"ref": bg_upload.json()["id"]},
                "feather_px": 0,
            },
            headers=client.auth,
        )
        assert p.status_code == 200
        assert Image.open(io.BytesIO(p.content)).size == (32, 24)

        r = recipe(
            ReplaceBackground(background_slot="bg"),
            slots=BG_SLOT,
            id="bg-api",
        ).model_dump(mode="json")
        r["source_image"] = {"ref": subject_id}
        job = client.post(
            "/api/jobs",
            json={"recipe": r, "bindings": {"bg": {"ref": bg_upload.json()["id"]}}},
            headers=client.auth,
        )
        assert job.status_code == 201
        done = client.wait_job(job.json()["id"])
        assert done["state"] == "done" and len(done["images"]) == 1
        gallery = client.get("/api/gallery", headers=client.auth).json()
        assert gallery["total"] == 1

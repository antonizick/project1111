"""Start from a photo: SDXL image-to-image on the Generate step (Phase 17b, ADR-0038).

Covers the additive schema, the compiler's bucket/size rules and presets (goldens for the
reviewed graphs), template capture's ``Start photo`` slot, the FakeEngine run, and the S5 rule for
edits of uploaded photos showing a face: a scripted detector and guard stand in for YuNet and the
classifiers (synthetic images only, S6).
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image
from tests.helpers import recipe
from tests.studio import png_bytes, studio_client
from tests.unit.test_recipe_compile import GOLDEN, check_links, golden_recipe, nodes_of, one
from tests.unit.test_steps_face_pose import runner_with

from p11.jobs.runner import EDIT_NEEDS_GUARD, JobControl, Runner, gallery_ref
from p11.media.faces import Face, FaceError
from p11.media.nsfw import GuardRefused, GuardUnavailable, Verdict
from p11.outputs import metadata
from p11.outputs.metadata import RunRecord
from p11.recipe.compile import CompileError, EngineGraph, compile, nearest_bucket, photo_output
from p11.recipe.model import (
    FileRef,
    Generate,
    Inpaint,
    Pose,
    Recipe,
    ReplaceBackground,
    SamplerOverride,
    Slot,
)
from p11.recipe.presets import IMG2IMG_MAX_PIXELS, IMG2IMG_PRESETS
from p11.recipe.registry import PROVISIONAL_DEFAULT_SET
from p11.templates.capture import capture_template

REG = PROVISIONAL_DEFAULT_SET
PHOTO = FileRef(ref="img-0123456789abcdef0123456789abcdef")
SIZES = {PHOTO.ref: (1920, 1080)}


def edit(preset: str | None = "change", **step: Any) -> Recipe:
    gen = Generate(prompt="the same house painted green", denoise_preset=preset, **step)
    return recipe(gen, source_image=PHOTO, id="photo-edit")


def graph(r: Recipe, sizes: dict[str, tuple[int, int]] | None = None, **kw: Any) -> EngineGraph:
    (g,) = compile(r, kw.pop("bindings", {}), REG, image_sizes=SIZES if sizes is None else sizes)
    assert isinstance(g, EngineGraph)
    check_links(g)
    return g


# ---------------------------------------------------------------------------------------------
# Schema


def test_text_to_image_is_unchanged() -> None:
    gen = Generate(prompt="a lighthouse")
    assert not gen.is_img2img
    assert (gen.image_slot, gen.denoise, gen.denoise_preset) == (None, None, None)
    # A recipe from before Phase 17b (no new keys) still loads and compiles to the same graph.
    raw = json.loads(golden_recipe("16:9-1920x1080", "photoreal").to_json())
    for key in ("image_slot", "denoise", "denoise_preset"):
        raw["steps"][0].pop(key)
    old = Recipe.model_validate(raw)
    assert old == golden_recipe("16:9-1920x1080", "photoreal")
    (g,) = compile(old, {}, REG, image_sizes=SIZES)
    assert isinstance(g, EngineGraph)
    assert "VAEEncode" not in {n["class_type"] for n in g.nodes.values()}
    golden = json.loads((GOLDEN / "16x9-1920x1080__photoreal.json").read_text())
    assert g.nodes == golden


@pytest.mark.parametrize(
    "fields", [{"image_slot": "photo"}, {"denoise": 0.4}, {"denoise_preset": "light"}]
)
def test_any_photo_field_turns_on_img2img(fields: dict[str, Any]) -> None:
    assert Generate(prompt="x", **fields).is_img2img


def test_schema_rejects_bad_values() -> None:
    with pytest.raises(ValueError):
        Generate(prompt="x", denoise=1.5)
    with pytest.raises(ValueError):
        Generate(prompt="x", denoise_preset="strong")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="mask"):
        recipe(Generate(prompt="x", image_slot="m"), slots=(Slot(name="m", kind="mask"),))
    with pytest.raises(ValueError, match="unknown slot"):
        recipe(Generate(prompt="x", image_slot="nope"))


def test_round_trip() -> None:
    r = edit("reimagine", batch_size=2)
    assert Recipe.model_validate_json(r.to_json()) == r


# ---------------------------------------------------------------------------------------------
# Buckets and sizes


@pytest.mark.parametrize(
    ("size", "bucket"),
    [
        ((1920, 1080), (1344, 768)),  # landscape 16:9
        ((4000, 3000), (1152, 896)),  # 4:3 photo
        ((1080, 1350), (896, 1152)),  # portrait 4:5
        ((3024, 4032), (896, 1152)),  # phone portrait 3:4
        ((800, 800), (1024, 1024)),  # square
        ((1080, 1920), (768, 1344)),  # phone screen 9:16
        ((3000, 1000), (1536, 640)),  # panorama
    ],
)
def test_nearest_sdxl_bucket(size: tuple[int, int], bucket: tuple[int, int]) -> None:
    assert nearest_bucket("sdxl", *size) == bucket


def test_sd15_buckets_and_zero_size() -> None:
    assert nearest_bucket("sd15", 1920, 1080) == (1024, 576)
    with pytest.raises(CompileError):
        nearest_bucket("sdxl", 0, 10)


def test_output_size_toward_the_photo_capped() -> None:
    assert photo_output((1344, 768), 1920, 1080) == (1904, 1088)
    # Larger than the biggest wallpaper preset: capped at 2560 x 1440's pixel count.
    w, h = photo_output((1344, 768), 6000, 3375)
    assert w * h <= IMG2IMG_MAX_PIXELS and w % 8 == 0 and h % 8 == 0 and w > 2400
    # Smaller than (or about) the bucket: the bucket, no upscale.
    assert photo_output((1024, 1024), 800, 800) == (1024, 1024)
    assert photo_output((1024, 1024), 1080, 1080) == (1024, 1024)


# ---------------------------------------------------------------------------------------------
# Graphs


@pytest.mark.parametrize("preset", ["light", "change", "reimagine"])
def test_golden_photo_edit_per_preset(preset: str) -> None:
    g = graph(edit(preset))
    base = next(n for n in g.nodes.values() if n.get("_meta", {}).get("title") == "base")
    assert base["inputs"]["denoise"] == IMG2IMG_PRESETS[preset]
    assert base["inputs"]["steps"] >= 5
    _golden(f"img2img__source-{preset}.json", g)


def test_photo_from_a_slot_and_its_size() -> None:
    r = recipe(
        Generate(prompt="a furnished room", image_slot="photo", denoise=0.6),
        slots=(Slot(name="photo", kind="image", label="Start photo"),),
        id="photo-slot",
    )
    g = graph(r, {PHOTO.ref: (1080, 1350)}, bindings={"photo": PHOTO})
    (inp,) = g.inputs
    assert (inp.source, inp.slot, inp.placeholder) == ("slot", "photo", "p11:slot:photo")
    scale = nodes_of(g, "ImageScale")[0]["inputs"]
    assert (scale["width"], scale["height"], scale["crop"]) == (896, 1152, "center")
    assert g.size == (1064, 1368)  # toward the photo's own 1080 x 1350
    base = next(n for n in g.nodes.values() if n.get("_meta", {}).get("title") == "base")
    assert base["inputs"]["denoise"] == 0.6
    _golden("img2img__slot-portrait.json", g)


def test_aspect_preset_is_ignored_and_upscale_chain_follows_the_photo() -> None:
    g = graph(edit("change", aspect="1:1-1024"))
    assert "EmptyLatentImage" not in {n["class_type"] for n in g.nodes.values()}
    first = nodes_of(g, "ImageScale")[0]["inputs"]
    assert (first["width"], first["height"]) == (1344, 768)
    assert g.size == (1904, 1088)
    assert nodes_of(g, "ImageUpscaleWithModel")  # the wallpaper "model" chain
    quality = graph(edit("change", quality=True))
    assert quality.size == (1904, 1088) and nodes_of(quality, "LatentUpscale")


def test_unknown_size_falls_back_to_the_aspect_preset() -> None:
    g = graph(edit("light", aspect="1:1-1024"), {})
    first = nodes_of(g, "ImageScale")[0]["inputs"]
    assert (first["width"], first["height"]) == (1024, 1024)
    assert g.size == (1024, 1024)


def test_batch_repeats_the_latent() -> None:
    g = graph(edit("change", batch_size=2))
    assert one(g, "RepeatLatentBatch")["amount"] == 2
    _golden("img2img__source-batch2.json", g)


def test_steps_override_and_custom_denoise() -> None:
    g = graph(edit(None, denoise=0.3, sampler=SamplerOverride(steps=12)))
    base = next(n for n in g.nodes.values() if n.get("_meta", {}).get("title") == "base")
    assert (base["inputs"]["steps"], base["inputs"]["denoise"]) == (12, 0.3)
    # A preset wins over a stray denoise value (as for inpaint).
    g = graph(edit("light", denoise=0.9))
    base = next(n for n in g.nodes.values() if n.get("_meta", {}).get("title") == "base")
    assert base["inputs"]["denoise"] == IMG2IMG_PRESETS["light"]


def test_pose_modifier_still_applies() -> None:
    r = recipe(
        Generate(prompt="a man in a fedora", denoise_preset="change"),
        Pose(pose_slot="pose"),
        slots=(Slot(name="pose", kind="image"),),
        source_image=PHOTO,
        id="photo-pose",
    )
    pose = FileRef(ref="img-fedcba9876543210fedcba9876543210")
    g = graph(r, {PHOTO.ref: (1024, 1024), pose.ref: (512, 512)}, bindings={"pose": pose})
    assert nodes_of(g, "ControlNetApplyAdvanced")
    assert {i.placeholder for i in g.inputs} == {"p11:source", "p11:slot:pose"}
    _golden("img2img__source-pose.json", g)


def test_no_photo_is_a_plain_error_and_never_the_previous_step() -> None:
    with pytest.raises(CompileError, match="add a photo"):
        compile(recipe(Generate(prompt="x", denoise_preset="light")), {}, REG)
    r = recipe(
        Generate(prompt="first"),
        Generate(prompt="second", denoise_preset="light"),
        id="two",
    )
    with pytest.raises(CompileError, match="add a photo"):
        compile(r, {}, REG)


def _golden(name: str, g: EngineGraph) -> None:
    path = GOLDEN / name
    pretty = json.dumps(g.nodes, sort_keys=True, indent=1, ensure_ascii=False) + "\n"
    if os.environ.get("P11_UPDATE_GOLDEN") == "1":
        path.write_text(pretty, encoding="utf-8")
    assert path.exists(), f"missing golden {name}; run with P11_UPDATE_GOLDEN=1 and review it"
    assert path.read_text(encoding="utf-8") == pretty


# ---------------------------------------------------------------------------------------------
# Templates


def test_capture_makes_a_start_photo_slot() -> None:
    record = RunRecord(recipe=edit("change"), bindings={}, seed=7)
    t = capture_template(record, name="Paint it")
    (slot,) = t.slots
    assert (slot.name, slot.kind, slot.label) == ("start_photo", "image", "Start photo")
    gen = t.steps[0]
    assert isinstance(gen, Generate) and gen.image_slot == "start_photo"
    assert t.source_image is None


def test_capture_leaves_text_to_image_generate_alone() -> None:
    r = recipe(
        Generate(prompt="a portrait"),
        Inpaint(mask_slot="mask"),
        slots=(Slot(name="mask", kind="mask"),),
        source_image=PHOTO,
        id="t2i-then-inpaint",
    )
    t = capture_template(RunRecord(recipe=r, bindings={}, seed=1), name="x")
    assert isinstance(t.steps[0], Generate) and t.steps[0].image_slot is None
    assert isinstance(t.steps[1], Inpaint) and t.steps[1].image_slot == "source"


# ---------------------------------------------------------------------------------------------
# Running on the FakeEngine


async def run(runner: Runner, r: Recipe, bindings: Any = None, parent: str | None = None):
    return await runner.run(
        recipe=r,
        bindings=bindings or {},
        count=1,
        template=None,
        parent=parent,
        control=JobControl(),
        publish=lambda *a: None,
        job_id="j",
        on_progress=lambda *a: None,
    )


class ScriptedGuard:
    def __init__(self, unsafe: bool = False) -> None:
        self.unsafe = unsafe
        self.seen: list[tuple[int, int]] = []

    def verdict(self, image: Image.Image) -> Verdict:
        self.seen.append(image.size)
        return Verdict(self.unsafe, (("scripted", 1.0 if self.unsafe else 0.0),))


class ScriptedDetector:
    def __init__(self, faces: bool) -> None:
        self.faces = faces
        self.calls = 0

    def detect(self, rgb: np.ndarray) -> list[Face]:
        self.calls += 1
        if not self.faces:
            return []
        return [Face((10.0, 10.0, 30.0, 30.0), ((15.0, 15.0),) * 5, 0.99)]


async def scripted(tmp_path: Path, *, faces: bool, unsafe: bool = False):
    runner = await runner_with(tmp_path)
    await runner.engine.start()
    guard, detector = ScriptedGuard(unsafe), ScriptedDetector(faces)
    runner.faces.guard = lambda: guard  # type: ignore[method-assign]
    runner.faces.detector = lambda: detector  # type: ignore[method-assign]
    return runner, guard, detector


def upload(runner: Runner, size: tuple[int, int] = (96, 64)) -> FileRef:
    return FileRef(ref=runner.inputs.add_image(png_bytes(size), "image").id)


def photo_edit(src: FileRef) -> Recipe:
    return recipe(
        Generate(prompt="a man in a leather jacket and fedora", denoise_preset="change"),
        source_image=src,
        id="photo-edit-run",
    )


async def test_photo_edit_runs_at_the_computed_size(tmp_path) -> None:
    runner, guard, _ = await scripted(tmp_path, faces=False)
    src = upload(runner, (1920, 1080))
    report = await run(runner, photo_edit(src))
    (image_id,) = report.image_ids
    entry = runner.gallery.get(image_id)
    assert entry is not None and (entry.width, entry.height) == (1904, 1088)
    assert guard.seen == []  # a photo with no face: no guard (A5)
    sidecar = metadata.read_sidecar(metadata.sidecar_path(runner.outputs_root / entry.path))
    assert not sidecar.likeness


async def test_uploaded_face_photo_is_guarded_and_marked(tmp_path) -> None:
    runner, guard, detector = await scripted(tmp_path, faces=True)
    report = await run(runner, photo_edit(upload(runner)))
    assert detector.calls == 1 and len(guard.seen) == 1
    entry = runner.gallery.get(report.image_ids[0])
    assert entry is not None
    sidecar = metadata.read_sidecar(metadata.sidecar_path(runner.outputs_root / entry.path))
    assert sidecar.likeness  # later edits of this image inherit the check (ADR-0037)


async def test_uploaded_face_photo_blocked_when_the_guard_says_sexual(tmp_path) -> None:
    runner, _, _ = await scripted(tmp_path, faces=True, unsafe=True)
    with pytest.raises(GuardRefused):
        await run(runner, photo_edit(upload(runner)))
    assert runner.gallery.count() == 0  # nothing was saved


async def test_missing_face_set_refuses_before_queueing(tmp_path) -> None:
    runner, _, _ = await scripted(tmp_path, faces=True)

    def missing():
        raise FaceError("The face detection model 'yunet-2023mar' is not installed.")

    runner.faces.detector = missing  # type: ignore[method-assign]
    src = upload(runner)
    with pytest.raises(GuardUnavailable, match="face safety models"):
        runner.validate(photo_edit(src), {})
    assert "p11 models install face" in EDIT_NEEDS_GUARD
    # And at run time (fails closed even if validation was skipped).
    with pytest.raises(GuardUnavailable):
        await run(runner, photo_edit(src))
    # Text-to-image never needs it (A5).
    runner.validate(recipe(Generate(prompt="a lighthouse")), {})


async def test_missing_guard_classifiers_also_refuse(tmp_path) -> None:
    runner, _, _ = await scripted(tmp_path, faces=False)

    def missing():
        raise GuardUnavailable("Face swap and face reference need their image check models")

    runner.faces.guard = missing  # type: ignore[method-assign]
    with pytest.raises(GuardUnavailable, match="face safety models"):
        runner.validate(photo_edit(upload(runner)), {})


async def test_non_likeness_gallery_source_is_not_checked(tmp_path) -> None:
    runner, guard, detector = await scripted(tmp_path, faces=True)
    first = await run(runner, recipe(Generate(prompt="a portrait", aspect="1:1-1024")))
    (image_id,) = first.image_ids
    entry = runner.gallery.get(image_id)
    assert entry is not None
    src = FileRef(ref=gallery_ref(image_id))
    runner.validate(photo_edit(src), {})  # no face set needed for P11's own images
    await run(runner, photo_edit(src), parent=entry.path)
    assert detector.calls == 0 and guard.seen == []


async def test_inpaint_and_background_on_an_uploaded_face_photo_are_guarded(tmp_path) -> None:
    runner, guard, detector = await scripted(tmp_path, faces=True)
    mask = runner.inputs.add_image(_mask_png((96, 64)), "mask")
    src = upload(runner)
    inpaint = recipe(
        Inpaint(mask_slot="mask", denoise_preset="balanced"),
        slots=(Slot(name="mask", kind="mask"),),
        source_image=src,
        id="inpaint-face",
    )
    await run(runner, inpaint, {"mask": FileRef(ref=mask.id)})
    assert detector.calls == 1 and len(guard.seen) == 1  # the mask itself is not "a photo"
    bg = recipe(ReplaceBackground(background_colour="#336699"), source_image=src, id="bg-face")
    await run(runner, bg)
    assert detector.calls == 2 and len(guard.seen) == 2


def test_inpaint_after_generate_does_not_check_the_source() -> None:
    r = recipe(
        Generate(prompt="a lighthouse", aspect="1:1-1024"),
        Inpaint(mask_slot="mask"),
        slots=(Slot(name="mask", kind="mask"),),
        id="gen-inpaint",
    )
    mask = FileRef(ref="img-0123456789abcdef0123456789abcdef")
    assert Runner.edited_uploads(r, {"mask": mask}) == []


def test_edited_uploads_lists_photos_only() -> None:
    a, b = FileRef(ref="img-" + "a" * 32), FileRef(ref="img-" + "b" * 32)
    r = recipe(
        ReplaceBackground(background_slot="bg"),
        slots=(Slot(name="bg", kind="background_image"),),
        source_image=a,
        id="bg-two",
    )
    assert Runner.edited_uploads(r, {"bg": b}) == [a, b]
    assert Runner.edited_uploads(photo_edit(FileRef(ref=gallery_ref(3))), {}) == []
    assert Runner.edited_uploads(recipe(Generate(prompt="t2i"), source_image=a), {}) == []


def _mask_png(size: tuple[int, int]) -> bytes:
    img = Image.new("L", size, 0)
    img.paste(255, (20, 10, 60, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------
# Studio API (no route change: the jobs API takes the new fields, user guide's curl example)


def test_jobs_api_runs_a_photo_edit(tmp_path) -> None:
    with studio_client(tmp_path) as c:
        up = c.post("/api/uploads?kind=image", headers=c.auth, content=png_bytes((1400, 800)))
        assert up.status_code == 201, up.text
        r = recipe(
            Generate(prompt="a modern furnished living room", denoise_preset="change"),
            source_image=FileRef(ref=up.json()["id"]),
            id="api-photo-edit",
        )
        job = c.post("/api/jobs", headers=c.auth, json={"recipe": r.model_dump(mode="json")})
        assert job.status_code == 201, job.text
        done = c.wait_job(job.json()["id"])
        assert done["state"] == "done", done
        info = c.get(f"/api/images/{done['images'][0]}/info", headers=c.auth).json()
        assert (info["width"], info["height"]) == (1344, 768)  # 1400 x 800: about the bucket
        record = c.get(f"/api/images/{done['images'][0]}/recipe", headers=c.auth).json()
        # The stub detector (``serve --fake``) finds a face in every upload: the guard ran.
        assert record["likeness"] is True

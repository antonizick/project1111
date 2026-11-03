"""Phase 10 inpainting: the compiler step, mask prep and paste-back, the job path and templates."""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from PIL import Image, ImageChops, ImageDraw
from pydantic import ValidationError
from tests.helpers import recipe
from tests.studio import generate_recipe, png_bytes, studio_client

from p11.media import inpaint as mi
from p11.outputs.metadata import RunRecord
from p11.recipe.compile import CompileError, MaskPrep, SlotBindingError, compile
from p11.recipe.model import FileRef, FixedSeed, Generate, Inpaint, ModelRef, SamplerOverride, Slot
from p11.recipe.presets import INPAINT_PRESETS
from p11.recipe.registry import PROVISIONAL_DEFAULT_SET
from p11.recipe.steps.inpaint import denoise_of
from p11.templates.capture import capture_template

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "compile"
REG = PROVISIONAL_DEFAULT_SET
MASK_SLOT = (Slot(name="mask", kind="mask"),)


def mask_png(
    size: tuple[int, int], box: tuple[int, int, int, int] | None, mode: str = "L"
) -> bytes:
    img = Image.new(mode, size, 0)
    if box is not None:
        ImageDraw.Draw(img).rectangle(box, fill=255 if mode == "L" else (255, 255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def nodes_of(graph: Any, cls: str) -> list[dict[str, Any]]:
    return [n["inputs"] for n in graph.nodes.values() if n["class_type"] == cls]


# ---------------------------------------------------------------------------------------------
# Schema


def test_schema_needs_exactly_one_mask() -> None:
    Inpaint(mask_slot="mask")
    Inpaint(mask_png=base64.b64encode(mask_png((8, 8), (1, 1, 4, 4))).decode())
    with pytest.raises(ValidationError, match="exactly one"):
        Inpaint()
    with pytest.raises(ValidationError, match="exactly one"):
        Inpaint(mask_slot="mask", mask_png="aGVsbG8gd29ybGQ=")
    with pytest.raises(ValidationError):
        Inpaint(mask_png="not base64 <svg>")


def test_older_v1_inpaint_documents_still_load() -> None:
    """The Phase 04 field set (no crop/blur/padding/sampler) validates with the new defaults."""
    step = Inpaint.model_validate(
        {"type": "inpaint", "mask_slot": "m", "prompt": "x", "denoise": 0.5, "grow_mask_px": 4}
    )
    assert step.crop and step.mask_blur_px == 12 and step.padding_px == 48


def test_denoise_presets_override_the_slider() -> None:
    assert denoise_of(Inpaint(mask_slot="m", denoise=0.42)) == 0.42
    for preset, value in INPAINT_PRESETS.items():
        assert denoise_of(Inpaint(mask_slot="m", denoise=0.42, denoise_preset=preset)) == value  # type: ignore[arg-type]
    assert INPAINT_PRESETS["subtle"] < INPAINT_PRESETS["balanced"] < INPAINT_PRESETS["major"]


# ---------------------------------------------------------------------------------------------
# Compiler

GOLDEN_CASES: dict[str, Any] = {
    "inpaint__source-subtle": lambda: recipe(
        Inpaint(mask_slot="mask", prompt="a red scarf", denoise_preset="subtle"),
        slots=MASK_SLOT,
        source_image=FileRef(ref="gallery/7"),
        id="golden-inpaint",
    ),
    "inpaint__after-generate": lambda: recipe(
        Generate(prompt="a lighthouse on a rocky coast", aspect="16:9-1920x1080"),
        Inpaint(mask_slot="mask", denoise_preset="balanced", crop=False),
        slots=MASK_SLOT,
        id="golden-inpaint-chain",
    ),
    "inpaint__fixed-mask-advanced": lambda: recipe(
        Inpaint(
            image_slot="photo",
            mask_png=base64.b64encode(mask_png((16, 16), (2, 2, 9, 9))).decode(),
            prompt="{{what}}",
            negative="blurry",
            denoise=0.8,
            model=ModelRef(manifest_id="juggernautxl9"),
            sampler=SamplerOverride(steps=12, cfg=4.0),
        ),
        slots=(Slot(name="photo", kind="image"), Slot(name="what", kind="text", default="moss")),
        id="golden-inpaint-fixed",
    ),
}
BINDINGS: dict[str, dict[str, Any]] = {
    "inpaint__source-subtle": {"mask": FileRef(ref="img-mask")},
    "inpaint__after-generate": {"mask": FileRef(ref="img-mask")},
    "inpaint__fixed-mask-advanced": {"photo": FileRef(ref="img-photo")},
}


@pytest.mark.parametrize("name", sorted(GOLDEN_CASES))
def test_inpaint_golden_graphs(name: str) -> None:
    graph = compile(GOLDEN_CASES[name](), BINDINGS[name], REG)[-1]
    assert graph.step_type == "inpaint" and graph.prep is not None
    for nid, node in graph.nodes.items():
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in graph.nodes and value[0] != nid
    path = GOLDEN / f"{name}.json"
    pretty = json.dumps(graph.nodes, sort_keys=True, indent=1, ensure_ascii=False) + "\n"
    if os.environ.get("P11_UPDATE_GOLDEN") == "1":
        path.write_text(pretty, encoding="utf-8")
    assert path.exists(), f"missing golden {name}; run with P11_UPDATE_GOLDEN=1 and review it"
    assert path.read_text(encoding="utf-8") == pretty


def test_graph_shape_and_prep() -> None:
    (g,) = compile(
        GOLDEN_CASES["inpaint__source-subtle"](), BINDINGS["inpaint__source-subtle"], REG
    )
    (ks,) = nodes_of(g, "KSampler")
    assert ks["denoise"] == INPAINT_PRESETS["subtle"] and ks["seed"] == 1111
    (cond,) = nodes_of(g, "InpaintModelConditioning")
    assert cond["noise_mask"] is True and ks["latent_image"][1] == 2
    (comp,) = nodes_of(g, "ImageCompositeMasked")
    assert comp["destination"] == cond["pixels"] and comp["mask"] == cond["mask"]
    (mask_node,) = nodes_of(g, "LoadImageMask")
    assert mask_node == {"image": "p11:slot:mask", "channel": "red"}
    assert [(i.source, i.kind) for i in g.inputs] == [("source", "image"), ("slot", "mask")]
    assert g.prep == MaskPrep(
        image="p11:source", mask="p11:slot:mask", grow_px=8, blur_px=12, crop=True,
        padding_px=48, work_pixels=1024 * 1024, max_upscale=4.0, max_pixels=2560 * 1440,
    )  # fmt: skip
    assert g.models == ("realvisxl5-lightning", "sdxl-vae-fp16-fix")


def test_chained_inpaint_takes_the_previous_output_and_its_prompt() -> None:
    gen, inp = compile(
        GOLDEN_CASES["inpaint__after-generate"](), BINDINGS["inpaint__after-generate"], REG
    )
    assert gen.prep is None and inp.inputs[0].source == "step" and inp.inputs[0].step == 0
    texts = [n["text"] for n in nodes_of(inp, "CLIPTextEncode")]
    assert "a lighthouse on a rocky coast" in texts[0]
    assert inp.prep is not None and inp.prep.crop is False


def test_fixed_mask_is_an_inline_input() -> None:
    r = GOLDEN_CASES["inpaint__fixed-mask-advanced"]()
    (g,) = compile(r, BINDINGS["inpaint__fixed-mask-advanced"], REG)
    inline = [i for i in g.inputs if i.source == "inline"]
    assert len(inline) == 1 and inline[0].kind == "mask" and inline[0].data is not None
    assert inline[0].data.startswith(b"\x89PNG")
    (ks,) = nodes_of(g, "KSampler")
    assert (ks["steps"], ks["cfg"], ks["denoise"]) == (12, 4.0, 0.8)
    assert nodes_of(g, "CLIPTextEncode")[0]["text"] == "moss"


def test_compile_errors_are_plain_english() -> None:
    no_mask = recipe(Inpaint(mask_slot="mask"), slots=MASK_SLOT, source_image=FileRef(ref="g"))
    with pytest.raises(SlotBindingError):
        compile(no_mask, {}, REG)
    no_image = recipe(Inpaint(mask_slot="mask"), slots=MASK_SLOT)
    with pytest.raises(CompileError, match="needs an input image"):
        compile(no_image, {"mask": FileRef(ref="img-m")}, REG)
    damaged = recipe(Inpaint(mask_png="aGVsbG8gd29ybGQ="), source_image=FileRef(ref="g"))
    with pytest.raises(CompileError, match="not a PNG"):
        compile(damaged, {}, REG)


# ---------------------------------------------------------------------------------------------
# Geometry (property tests)

sizes = st.tuples(st.integers(1, 4000), st.integers(1, 4000))


@given(size=sizes, data=st.data(), padding=st.integers(0, 1024))
def test_pad_box_stays_inside_and_contains_the_mask(size: Any, data: Any, padding: int) -> None:
    w, h = size
    x0 = data.draw(st.integers(0, w - 1))
    y0 = data.draw(st.integers(0, h - 1))
    x1 = data.draw(st.integers(x0 + 1, w))
    y1 = data.draw(st.integers(y0 + 1, h))
    bx0, by0, bx1, by1 = mi.pad_box((x0, y0, x1, y1), size, padding)
    assert 0 <= bx0 <= x0 and 0 <= by0 <= y0 and x1 <= bx1 <= w and y1 <= by1 <= h
    assert bx0 == max(0, x0 - padding) and bx1 == min(w, x1 + padding)


@given(box=sizes, upscale=st.booleans())
def test_work_size_is_a_multiple_of_8_and_fits(box: Any, upscale: bool) -> None:
    ww, hh = mi.work_size(
        box, work_pixels=1024 * 1024, max_upscale=4.0, max_pixels=2560 * 1440, upscale=upscale
    )
    assert ww % 8 == 0 and hh % 8 == 0 and ww >= 8 and hh >= 8
    assert ww * hh <= 2560 * 1440
    w, h = box
    if w * h > 2560 * 1440:
        assert ww < w + 8 and hh < h + 8
    elif not upscale or w * h >= 1024 * 1024:
        assert abs(ww - w) <= 4 + 8 and abs(hh - h) <= 4 + 8
    else:
        assert ww <= w * 4 + 8 and hh <= h * 4 + 8


def test_work_size_upscales_small_crops_and_shrinks_huge_ones() -> None:
    kw = {"work_pixels": 1024 * 1024, "max_upscale": 4.0, "max_pixels": 2560 * 1440}
    assert mi.work_size((256, 256), **kw) == (1024, 1024)
    assert mi.work_size((100, 50), **kw) == (400, 200)
    assert mi.work_size((1920, 1080), **kw) == (1920, 1080)
    big = mi.work_size((4000, 3000), **kw)
    assert big[0] * big[1] <= 2560 * 1440 and abs(big[0] / big[1] - 4 / 3) < 0.02
    with pytest.raises(ValueError):
        mi.work_size((0, 10), **kw)


# ---------------------------------------------------------------------------------------------
# Prepare and stitch

PREP = MaskPrep("p11:source", "p11:slot:mask", 8, 6, True, 32, 1024 * 1024, 4.0, 2560 * 1440)


def noisy_image(size: tuple[int, int]) -> bytes:
    img = Image.effect_noise(size, 60).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def red_result(prepared: mi.Prepared, size: tuple[int, int] | None = None) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size or prepared.work, "red").save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.parametrize("crop", [True, False])
def test_stitch_keeps_unmasked_pixels_exactly(crop: bool) -> None:
    src = noisy_image((640, 360))
    prep = MaskPrep(**{**PREP.__dict__, "crop": crop})
    prepared = mi.prepare(src, mask_png((640, 360), (300, 150, 360, 200)), prep)
    if crop:
        x0, y0, x1, y1 = prepared.box
        soft = prepared.soft.getbbox()
        assert soft is not None and (x0, y0) == (soft[0] - 32, soft[1] - 32)
        assert (x1, y1) == (soft[2] + 32, soft[3] + 32)
        assert prepared.work[0] * prepared.work[1] > (prepared.box[2] - prepared.box[0]) * (
            prepared.box[3] - prepared.box[1]
        )
    else:
        assert prepared.box == (0, 0, 640, 360) and prepared.work == (640, 360)
    out = Image.open(io.BytesIO(mi.stitch(prepared, red_result(prepared)))).convert("RGB")
    original = Image.open(io.BytesIO(src)).convert("RGB")
    assert out.size == original.size
    outside = prepared.soft.point(lambda v: 255 if v == 0 else 0)
    diff = ImageChops.difference(out, original)
    assert ImageChops.multiply(diff.convert("L"), outside).getbbox() is None
    # Inside the painted rectangle the result shows through.
    assert out.getpixel((330, 175)) == (255, 0, 0)


def test_stitch_handles_a_result_floored_by_the_vae() -> None:
    prepared = mi.prepare(noisy_image((203, 101)), mask_png((203, 101), (50, 20, 90, 60)), PREP)
    small = red_result(prepared, (prepared.work[0] - 8, prepared.work[1] - 8))
    out = Image.open(io.BytesIO(mi.stitch(prepared, small)))
    assert out.size == (203, 101)


def test_mask_is_resized_grown_and_blurred() -> None:
    src = noisy_image((400, 200))
    prepared = mi.prepare(src, mask_png((200, 100), (50, 25, 60, 35)), PREP)
    bbox = prepared.soft.getbbox()
    assert bbox is not None and bbox[0] < 100 - 8 and bbox[2] > 121 + 8


def test_rgba_mask_uses_alpha() -> None:
    m = mask_png((64, 64), (10, 10, 20, 20), mode="RGBA")
    assert mi._open(m, "L").getbbox() == (10, 10, 21, 21)


def test_empty_mask_is_refused() -> None:
    with pytest.raises(mi.MaskError, match="empty"):
        mi.prepare(noisy_image((64, 64)), mask_png((64, 64), None), PREP)
    with pytest.raises(mi.MaskError, match="empty"):
        mi.check_mask(mask_png((64, 64), None))
    with pytest.raises(mi.MaskError, match="readable"):
        mi.check_mask(b"nope")
    mi.check_mask(mask_png((64, 64), (1, 1, 2, 2)))


def test_compact_mask_is_small_and_greyscale() -> None:
    data = mi.compact_mask(mask_png((2560, 1440), (100, 100, 900, 700)))
    img = Image.open(io.BytesIO(data))
    assert img.mode == "L" and img.size == (1024, 576) and len(data) < 20_000
    assert mi.compact_mask(mask_png((64, 32), (1, 1, 5, 5))) != b""


# ---------------------------------------------------------------------------------------------
# Job path on the FakeEngine (Studio API)


def inpaint_job(mask_ref: str, image_id: int, **step: Any) -> dict[str, Any]:
    r = recipe(
        Inpaint(mask_slot="mask", prompt="a red scarf", denoise_preset="balanced", **step),
        slots=MASK_SLOT,
        source_image=FileRef(ref=f"gallery/{image_id}"),
        seed=FixedSeed(value=5),  # not the source's seed, so the fake paints another colour
        id="r-inpaint",
        name="Inpaint",
    )
    return {"recipe": r.model_dump(mode="json"), "bindings": {"mask": {"ref": mask_ref}},
            "parent": image_id}  # fmt: skip


@pytest.fixture
def client(tmp_path):  # type: ignore[no-untyped-def]
    with studio_client(tmp_path) as c:
        job = c.post("/api/jobs", headers=c.auth, json={"recipe": generate_recipe()}).json()
        assert c.wait_job(job["id"])["state"] == "done"
        yield c


def _upload_mask(c: Any, size: tuple[int, int], box: tuple[int, int, int, int] | None) -> str:
    r = c.post("/api/uploads?kind=mask", headers=c.auth, content=mask_png(size, box))
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _image(c: Any, image_id: int) -> Image.Image:
    data = c.get(f"/api/images/{image_id}", headers=c.auth).content
    return Image.open(io.BytesIO(data)).convert("RGB")


@pytest.mark.parametrize("crop", [True, False])
def test_inpaint_job_makes_a_child_with_unmasked_pixels_intact(client: Any, crop: bool) -> None:
    c = client
    (source,) = c.get("/api/gallery", headers=c.auth).json()["items"]
    w, h = source["width"], source["height"]
    mask = _upload_mask(c, (w, h), (400, 400, 520, 480))
    job = c.post("/api/jobs", headers=c.auth, json=inpaint_job(mask, source["id"], crop=crop))
    assert job.status_code == 201, job.text
    done = c.wait_job(job.json()["id"])
    assert done["state"] == "done", done
    (child_id,) = done["images"]
    child = c.get(f"/api/images/{child_id}/info", headers=c.auth).json()
    assert child["parent_id"] == source["id"] and (child["width"], child["height"]) == (w, h)
    before, after = _image(c, source["id"]), _image(c, child_id)
    diff = ImageChops.difference(before, after).convert("L").getbbox()
    assert diff is not None
    assert diff[0] >= 400 - 8 - 40 and diff[2] <= 521 + 8 + 40  # inside mask + grow + blur band
    # The fake's mask upload went up as a mask and the engine saw the working size.
    uploaded = [n for n in c.engine.uploads if n.startswith("p11-mask-")]
    assert uploaded


def test_empty_mask_is_refused_at_submit(client: Any) -> None:
    c = client
    (source,) = c.get("/api/gallery", headers=c.auth).json()["items"]
    mask = _upload_mask(c, (64, 64), None)
    r = c.post("/api/jobs", headers=c.auth, json=inpaint_job(mask, source["id"]))
    assert r.status_code == 422 and r.json()["code"] == "input.mask"


@pytest.mark.parametrize("mode", ["slot", "fixed"])
def test_template_from_an_inpaint_reruns(client: Any, mode: str) -> None:
    c = client
    (source,) = c.get("/api/gallery", headers=c.auth).json()["items"]
    mask = _upload_mask(c, (source["width"], source["height"]), (100, 100, 300, 260))
    done = c.wait_job(
        c.post("/api/jobs", headers=c.auth, json=inpaint_job(mask, source["id"])).json()["id"]
    )
    (child_id,) = done["images"]
    t = c.post(
        "/api/templates/from-image",
        headers=c.auth,
        json={"image_id": child_id, "name": "Scarf fix", "mask": mode, "seed": "random"},
    )
    assert t.status_code == 201, t.text
    tpl = t.json()
    names = {s["name"]: s["kind"] for s in tpl["recipe"]["slots"]}
    step = tpl["recipe"]["steps"][0]
    if mode == "slot":
        assert names == {"mask": "mask", "source": "image"} and step["mask_png"] is None
        bindings = {"source": {"ref": f"gallery/{source['id']}"}, "mask": {"ref": mask}}
    else:
        assert names == {"source": "image"} and step["mask_slot"] is None
        assert len(step["mask_png"]) < 20_000
        bindings = {"source": {"ref": f"gallery/{source['id']}"}}
    run = c.post(
        "/api/jobs",
        headers=c.auth,
        json={"recipe": tpl["recipe"], "bindings": bindings, "template": "scarf-fix"},
    )
    assert run.status_code == 201, run.text
    assert c.wait_job(run.json()["id"])["state"] == "done"


def test_fixed_mask_needs_the_runs_mask(client: Any, tmp_path: Path) -> None:
    c = client
    (source,) = c.get("/api/gallery", headers=c.auth).json()["items"]
    mask = _upload_mask(c, (source["width"], source["height"]), (10, 10, 50, 50))
    done = c.wait_job(
        c.post("/api/jobs", headers=c.auth, json=inpaint_job(mask, source["id"])).json()["id"]
    )
    c.studio.inputs.get(mask).path.unlink()
    r = c.post(
        "/api/templates/from-image",
        headers=c.auth,
        json={"image_id": done["images"][0], "name": "x", "mask": "fixed"},
    )
    assert r.status_code == 422


def test_capture_keeps_other_slots_and_a_used_mask_slot() -> None:
    step = Inpaint(mask_slot="mask")
    r = recipe(step, slots=MASK_SLOT, source_image=FileRef(ref="gallery/1"))
    record = RunRecord(
        recipe=r, bindings={"mask": FileRef(ref="img-m")}, seed=3, model_hashes={},
        engine_version="0.43.0", p11_version="0", timings={}, step_outputs=(),
    )  # fmt: skip
    t = capture_template(record, name="x", masks={"mask": png_bytes()})
    assert [s.name for s in t.slots] == ["source"]
    assert t.steps[0].image_slot == "source"  # type: ignore[union-attr]
    t2 = capture_template(record, name="x")
    assert [s.name for s in t2.slots] == ["mask", "source"]

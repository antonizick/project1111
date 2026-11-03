"""The face, pose and reference steps through the compiler, the runner and the API (Phase 12).

Covers the compiled graphs (golden shape), the S5 guard at every entry point the API offers, and
the one rule that matters most: nothing can turn the guard off.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image
from tests.helpers import recipe
from tests.studio import generate_recipe, png_bytes, studio_client

from p11.engine.fake import FakeEngine
from p11.jobs.runner import JobControl, Runner
from p11.media.control import Controls
from p11.media.faces import FaceKit
from p11.media.inputs import InputStore
from p11.media.nsfw import STUB_MARKER, GuardRefused
from p11.media.segment import Segmenters
from p11.outputs.index import GalleryIndex
from p11.recipe.compile import EngineGraph, LocalStep, compile
from p11.recipe.model import (
    FaceRestore,
    FaceSwap,
    FileRef,
    Generate,
    Pose,
    Reference,
    Slot,
)
from p11.recipe.presets import (
    DEFAULT_CLIPVISION,
    DEFAULT_CONTROLNET,
    DEFAULT_GUARD_CLASSIFIERS,
    DEFAULT_IPADAPTER,
    DEFAULT_IPADAPTER_FACE,
    DEFAULT_RECOGNIZER,
    DEFAULT_RESTORER,
    DEFAULT_SWAPPER,
)
from p11.recipe.registry import PROVISIONAL_DEFAULT_SET

REG = PROVISIONAL_DEFAULT_SET
SLOTS = (
    Slot(name="face", kind="face_image"),
    Slot(name="pose", kind="image"),
    Slot(name="ref", kind="image"),
)
FILES = {n: FileRef(ref=f"{n}-1") for n in ("face", "pose", "ref")}


def unsafe_png(size: tuple[int, int] = (64, 64)) -> bytes:
    """A synthetic test image the stub guard calls unsafe (magenta corners; not a real photo)."""
    im = Image.new("RGB", size, (30, 30, 30))
    for x, y in ((0, 0), (size[0] - 1, 0), (0, size[1] - 1), (size[0] - 1, size[1] - 1)):
        im.putpixel((x, y), STUB_MARKER)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def one_graph(*steps, bindings=FILES) -> EngineGraph:
    items = compile(recipe(*steps, slots=SLOTS), bindings, REG, seed=7)
    assert len(items) == 1 and isinstance(items[0], EngineGraph)
    return items[0]


# ---------------------------------------------------------------------------------------------
# face_swap / face_restore


def test_face_swap_is_a_local_step_with_the_whole_face_model_set() -> None:
    items = compile(
        recipe(FaceSwap(face_slot="face"), source_image=FileRef(ref="target"), slots=SLOTS),
        FILES,
        REG,
        seed=7,
    )
    assert len(items) == 1
    item = items[0]
    assert isinstance(item, LocalStep)
    assert item.op == "face_swap"
    assert item.step_type == "face_swap"
    assert item.params["restore"] is True
    assert item.params["swapper_model"] == DEFAULT_SWAPPER
    assert item.params["restore_model"] == DEFAULT_RESTORER
    assert set(item.models) == {
        DEFAULT_SWAPPER,
        DEFAULT_RESTORER,
        DEFAULT_RECOGNIZER,
        "yunet-2023mar",
        *DEFAULT_GUARD_CLASSIFIERS,
    }
    assert {i.placeholder for i in item.inputs} == {"image", "face"}
    assert next(i for i in item.inputs if i.placeholder == "image").source == "source"
    assert next(i for i in item.inputs if i.placeholder == "face").source == "slot"


def test_face_swap_without_restore_drops_the_restorer() -> None:
    items = compile(
        recipe(
            FaceSwap(face_slot="face", restore=False), source_image=FileRef(ref="t"), slots=SLOTS
        ),
        FILES,
        REG,
        seed=7,
    )
    item = items[0]
    assert isinstance(item, LocalStep)
    assert item.params["restore_model"] is None
    assert DEFAULT_RESTORER not in item.models


def test_face_restore_compiles_too() -> None:
    items = compile(
        recipe(FaceRestore(visibility=0.4), source_image=FileRef(ref="t"), slots=SLOTS),
        FILES,
        REG,
        seed=7,
    )
    item = items[0]
    assert isinstance(item, LocalStep) and item.op == "face_restore"
    assert item.params == {
        "face_index": None,
        "visibility": 0.4,
        "restore_model": DEFAULT_RESTORER,
    }


# ---------------------------------------------------------------------------------------------
# pose


def test_pose_adds_the_union_control_net_and_preprocesses_the_picture() -> None:
    g = one_graph(Generate(prompt="a dancer"), Pose(pose_slot="pose"))
    classes = [n["class_type"] for n in g.nodes.values()]
    for wanted in (
        "ControlNetLoader",
        "SetUnionControlNetType",
        "ControlNetApplyAdvanced",
        "LoadImage",
    ):
        assert wanted in classes
    union = next(n for n in g.nodes.values() if n["class_type"] == "SetUnionControlNetType")
    assert union["inputs"]["type"] == "openpose"
    applied = next(n for n in g.nodes.values() if n["class_type"] == "ControlNetApplyAdvanced")
    assert applied["inputs"]["strength"] == pytest.approx(0.8)
    assert applied["inputs"]["start_percent"] == 0.0
    assert applied["inputs"]["end_percent"] == 1.0
    # The picture is read from the pose slot and prepared in P11 before it reaches the engine.
    [pose_input] = [i for i in g.inputs if i.slot == "pose"]
    assert pose_input.transform == "pose"
    # The sampler's conditioning comes out of the control net.
    applied_id = next(k for k, v in g.nodes.items() if v is applied)
    sampler = next(n for n in g.nodes.values() if n["class_type"] == "KSampler")
    assert sampler["inputs"]["positive"] == [applied_id, 0]
    assert sampler["inputs"]["negative"] == [applied_id, 1]
    assert DEFAULT_CONTROLNET in g.models


def test_pose_without_preprocess_uses_the_picture_as_it_is() -> None:
    g = one_graph(Generate(prompt="x"), Pose(pose_slot="pose", preprocess=False))
    assert next(i for i in g.inputs if i.slot == "pose").transform is None


def test_pose_depth_and_canny_pick_their_union_type_and_preprocessor() -> None:
    for control, union_type, transform in [
        ("depth", "depth", "depth"),
        ("canny", "canny/lineart/anime_lineart/mlsd", "canny"),
    ]:
        g = one_graph(Generate(prompt="x"), Pose(pose_slot="pose", control=control))
        union = next(n for n in g.nodes.values() if n["class_type"] == "SetUnionControlNetType")
        assert union["inputs"]["type"] == union_type
        assert next(i for i in g.inputs if i.slot == "pose").transform == transform


def test_pose_needs_a_generate_step_before_it() -> None:
    from pydantic import ValidationError

    from p11.recipe.model import Recipe

    with pytest.raises(ValidationError, match="must follow a generate step"):
        Recipe.new("x", [Pose(pose_slot="pose")], slots=(Slot(name="pose", kind="image"),))


# ---------------------------------------------------------------------------------------------
# reference


def test_reference_adds_the_ip_adapter_path() -> None:
    g = one_graph(Generate(prompt="x"), Reference(image_slot="ref"))
    classes = {n["class_type"] for n in g.nodes.values()}
    assert {
        "P11IPAdapterLoader",
        "CLIPVisionLoader",
        "CLIPVisionEncode",
        "P11IPAdapterApply",
    } <= classes
    loader = next(n for n in g.nodes.values() if n["class_type"] == "P11IPAdapterLoader")
    assert loader["inputs"]["ipadapter_file"] == "ip-adapter-plus-sdxl.safetensors"
    clip = next(n for n in g.nodes.values() if n["class_type"] == "CLIPVisionLoader")
    assert clip["inputs"]["clip_name"] == DEFAULT_CLIPVISION + ".safetensors"
    encode = next(n for n in g.nodes.values() if n["class_type"] == "CLIPVisionEncode")
    assert encode["inputs"]["crop"] == "none"
    apply = next(n for n in g.nodes.values() if n["class_type"] == "P11IPAdapterApply")
    assert apply["inputs"]["weight"] == pytest.approx(0.7)
    assert apply["inputs"]["start"] == 0.0 and apply["inputs"]["end"] == 1.0
    assert {DEFAULT_IPADAPTER, DEFAULT_CLIPVISION} <= set(g.models)
    # The patched model is what the sampler uses.
    sampler = next(n for n in g.nodes.values() if n["class_type"] == "KSampler")
    apply_id = next(k for k, v in g.nodes.items() if v is apply)
    assert sampler["inputs"]["model"] == [apply_id, 0]
    assert next(i for i in g.inputs if i.slot == "ref").transform == "reference"


def test_reference_mode_picks_the_face_adapter_for_a_character() -> None:
    g = one_graph(Generate(prompt="x"), Reference(image_slot="ref", mode="character", weight=1.0))
    loader = next(n for n in g.nodes.values() if n["class_type"] == "P11IPAdapterLoader")
    assert loader["inputs"]["ipadapter_file"] == "ip-adapter-plus-face-sdxl.safetensors"
    assert DEFAULT_IPADAPTER_FACE in g.models


def test_pose_and_reference_fold_into_the_generate_graph() -> None:
    """A generate with both modifiers is still one graph, with both chains in it."""
    g = one_graph(
        Generate(prompt="x"), Pose(pose_slot="pose"), Reference(image_slot="ref", mode="style")
    )
    assert g.step_type == "generate"
    classes = [n["class_type"] for n in g.nodes.values()]
    assert "ControlNetApplyAdvanced" in classes and "P11IPAdapterApply" in classes


# ---------------------------------------------------------------------------------------------
# The guard, at every entry point


async def runner_with(root) -> Runner:
    gallery = GalleryIndex(root / "g.db")
    inputs = InputStore(root / "in")
    return Runner(
        FakeEngine(),
        lambda: REG,
        root / "out",
        gallery,
        inputs,
        segmenters=Segmenters(stub=True),
        faces=FaceKit(stub=True),
        controls=Controls(stub=True),
    )


def swap_recipe(target_ref: str, face_ref: str):
    return recipe(
        FaceSwap(face_slot="face"),
        slots=(Slot(name="face", kind="face_image"),),
        source_image=FileRef(ref=target_ref),
        id="swap-test",
    )


async def test_the_guard_refuses_before_the_job_is_queued(tmp_path) -> None:
    runner = await runner_with(tmp_path)
    target = runner.inputs.add_image(unsafe_png(), "image")
    face = runner.inputs.add_image(png_bytes((32, 32)), "image")
    with pytest.raises(GuardRefused):
        runner.validate(swap_recipe(target.id, face.id), {"face": FileRef(ref=face.id)})


async def test_the_guard_refuses_inside_the_run_too(tmp_path) -> None:
    """Even a recipe that somehow got past validation is checked again before the swap."""
    runner = await runner_with(tmp_path)
    target = runner.inputs.add_image(unsafe_png(), "image")
    face = runner.inputs.add_image(png_bytes((32, 32)), "image")
    report = []
    with pytest.raises(GuardRefused):
        await runner.run(
            recipe=swap_recipe(target.id, face.id),
            bindings={"face": FileRef(ref=face.id)},
            count=1,
            template=None,
            parent=None,
            control=JobControl(),
            publish=lambda *a: None,
            job_id="j1",
            on_progress=lambda *a: report.append(a),
        )
    assert report == []  # nothing was reported: it never started making pictures


def test_the_api_refuses_an_unsafe_face_swap(tmp_path) -> None:
    with studio_client(tmp_path) as client:
        target = client.post("/api/uploads?kind=image", content=unsafe_png(), headers=client.auth)
        face = client.post(
            "/api/uploads?kind=image", content=png_bytes((32, 32)), headers=client.auth
        )
        body = generate_recipe()
        body["id"] = "swap-api"
        body["name"] = "Swap"
        body["source_image"] = {"ref": target.json()["id"]}
        body["slots"] = [{"name": "face", "kind": "face_image", "label": None,
                          "required": True, "default": None}]  # fmt: skip
        body["steps"] = [{"type": "face_swap", "face_slot": "face", "image_slot": None,
                          "source_face_index": 0, "target_face_index": 0, "swapper_model": None,
                          "blend": 1.0, "restore": True, "restore_model": None,
                          "restore_visibility": 1.0}]  # fmt: skip
        res = client.post(
            "/api/jobs",
            json={"recipe": body, "bindings": {"face": {"ref": face.json()["id"]}}},
            headers=client.auth,
        )
        assert res.status_code == 422, res.text
        problem = res.json()
        assert problem["code"] == "face.guard"
        assert "nude or sexual" in problem["message"]


def test_the_guard_models_are_required_not_optional(tmp_path) -> None:
    """A missing guard model refuses the swap (fail closed) instead of running without a guard."""
    from p11.media.nsfw import GuardUnavailable, build_guard

    with pytest.raises(GuardUnavailable, match="Install them"):
        build_guard(lambda mid: tmp_path / f"{mid}.onnx")


def test_the_api_runs_a_face_swap_when_the_target_is_fine(tmp_path) -> None:
    with studio_client(tmp_path) as client:
        target = client.post(
            "/api/uploads?kind=image", content=png_bytes((64, 64), "navy"), headers=client.auth
        )
        face = client.post(
            "/api/uploads?kind=image", content=png_bytes((32, 32), "crimson"), headers=client.auth
        )
        body = generate_recipe()
        body["id"] = "swap-ok"
        body["name"] = "Swap"
        body["seed"] = {"kind": "fixed", "value": 5}
        body["source_image"] = {"ref": target.json()["id"]}
        body["slots"] = [{"name": "face", "kind": "face_image", "label": None,
                          "required": True, "default": None}]  # fmt: skip
        body["steps"] = [{"type": "face_swap", "face_slot": "face", "image_slot": None,
                          "source_face_index": 0, "target_face_index": 0, "swapper_model": None,
                          "blend": 1.0, "restore": True, "restore_model": None,
                          "restore_visibility": 1.0}]  # fmt: skip
        res = client.post(
            "/api/jobs",
            json={"recipe": body, "bindings": {"face": {"ref": face.json()["id"]}}},
            headers=client.auth,
        )
        assert res.status_code == 201, res.text
        job = client.wait_job(res.json()["id"])
        assert job["state"] == "done", job
        assert job["images"]


def test_a_template_can_run_a_face_swap_and_still_hits_the_guard(tmp_path) -> None:
    """Templates have no way around the guard either (S5)."""
    with studio_client(tmp_path) as client:
        target = client.post("/api/uploads?kind=image", content=unsafe_png(), headers=client.auth)
        face = client.post(
            "/api/uploads?kind=image", content=png_bytes((32, 32)), headers=client.auth
        )
        body = generate_recipe()
        body["id"] = "swap-template"
        body["name"] = "Swap template"
        body["source_image"] = {"ref": target.json()["id"]}
        body["slots"] = [{"name": "face", "kind": "face_image", "label": None,
                          "required": True, "default": None}]  # fmt: skip
        body["steps"] = [{"type": "face_swap", "face_slot": "face", "image_slot": None,
                          "source_face_index": 0, "target_face_index": 0, "swapper_model": None,
                          "blend": 1.0, "restore": False, "restore_model": None,
                          "restore_visibility": 1.0}]  # fmt: skip
        made = client.post("/api/templates", json=body, headers=client.auth)
        assert made.status_code in (200, 201), made.text
        run = client.post(
            "/api/jobs",
            json={
                "recipe": body,
                "bindings": {"face": {"ref": face.json()["id"]}},
                "template": made.json()["id"],
            },
            headers=client.auth,
        )
        assert run.status_code == 422
        assert run.json()["code"] == "face.guard"


# ---------------------------------------------------------------------------------------------
# The look-before-you-run routes


def test_face_detect_reports_the_faces_for_the_picker(tmp_path) -> None:
    with studio_client(tmp_path) as client:
        up = client.post(
            "/api/uploads?kind=image", content=png_bytes((80, 60)), headers=client.auth
        )
        res = client.post("/api/face/detect", json={"ref": up.json()["id"]}, headers=client.auth)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["width"] == 80 and body["height"] == 60
        assert isinstance(body["faces"], list)


def test_pose_extract_and_render_round_trip(tmp_path) -> None:
    with studio_client(tmp_path) as client:
        up = client.post(
            "/api/uploads?kind=image", content=png_bytes((80, 60)), headers=client.auth
        )
        found = client.post("/api/pose/extract", json={"ref": up.json()["id"]}, headers=client.auth)
        assert found.status_code == 200, found.text
        body = found.json()
        assert len(body["people"][0]) == 18
        drawn = client.post(
            "/api/pose/render",
            json={"people": body["people"], "width": 200, "height": 300},
            headers=client.auth,
        )
        assert drawn.status_code == 200
        assert drawn.headers["content-type"] == "image/png"
        im = Image.open(io.BytesIO(drawn.content))
        assert im.size == (200, 300)
        assert im.convert("L").getextrema()[1] > 0  # something was drawn


def test_pose_render_refuses_a_malformed_pose(tmp_path) -> None:
    with studio_client(tmp_path) as client:
        bad = client.post(
            "/api/pose/render",
            json={"people": [[None] * 17], "width": 100, "height": 100},
            headers=client.auth,
        )
        assert bad.status_code == 422
        assert bad.json()["code"] == "control.map"


def test_the_api_runs_a_pose_and_a_reference_job(tmp_path) -> None:
    """FakeEngine e2e for the two generation tools: they are ordinary jobs with modifiers."""
    with studio_client(tmp_path) as client:
        pose_ref = client.post(
            "/api/uploads?kind=image", content=png_bytes((64, 96), "black"), headers=client.auth
        ).json()["id"]
        ref_ref = client.post(
            "/api/uploads?kind=image", content=png_bytes((64, 64), "teal"), headers=client.auth
        ).json()["id"]
        for extra, bindings, slot, kind in [
            (
                {
                    "type": "pose",
                    "pose_slot": "pose",
                    "preprocess": True,
                    "control": "openpose",
                    "controlnet": None,
                    "strength": 0.8,
                    "start": 0.0,
                    "end": 1.0,
                },
                {"pose": {"ref": pose_ref}},
                "pose",
                "image",
            ),
            (
                {
                    "type": "reference",
                    "image_slot": "ref",
                    "mode": "style",
                    "ipadapter": None,
                    "weight": 0.7,
                    "start": 0.0,
                    "end": 1.0,
                },
                {"ref": {"ref": ref_ref}},
                "ref",
                "image",
            ),
        ]:
            body = generate_recipe()
            body["id"] = f"ui-{slot}"
            body["name"] = f"UI {slot}"
            body["slots"] = [
                {"name": slot, "kind": kind, "label": None, "required": True, "default": None}
            ]
            body["steps"] = [
                {
                    "type": "generate",
                    "prompt": "a lighthouse",
                    "negative": "",
                    "style": "photoreal",
                    "aspect": "1:1-1024",
                    "model": None,
                    "vae": None,
                    "loras": [],
                    "sampler": None,
                    "chain": None,
                    "quality": False,
                    "batch_size": 1,
                },
                extra,
            ]
            res = client.post(
                "/api/jobs", json={"recipe": body, "bindings": bindings}, headers=client.auth
            )
            assert res.status_code == 201, res.text
            job = client.wait_job(res.json()["id"])
            assert job["state"] == "done", job
            assert job["images"]


def test_the_api_runs_face_restore(tmp_path) -> None:
    with studio_client(tmp_path) as client:
        up = client.post(
            "/api/uploads?kind=image", content=png_bytes((64, 64)), headers=client.auth
        )
        body = generate_recipe()
        body["id"] = "restore-api"
        body["name"] = "Restore"
        body["source_image"] = {"ref": up.json()["id"]}
        body["slots"] = []
        body["steps"] = [
            {
                "type": "face_restore",
                "image_slot": None,
                "face_index": 0,
                "restore_model": None,
                "visibility": 0.8,
            }
        ]
        res = client.post("/api/jobs", json={"recipe": body}, headers=client.auth)
        assert res.status_code == 201, res.text
        job = client.wait_job(res.json()["id"])
        assert job["state"] == "done", job
        assert job["images"]

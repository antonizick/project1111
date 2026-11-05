"""S5 beyond the swap itself (Phase 16, ADR-0037): pictures that carry a person's likeness.

A face reference (IP-Adapter Plus Face) keeps a person recognisable in a generated picture, and an
edit of a face-swapped picture works on that person's face. Both are checked by the S5 guard like
the swap's own result: inside the run, for every later step, and for later jobs made from such a
gallery image. Uses a scripted guard (no real photos, S6).
"""

from __future__ import annotations

import subprocess

import pytest
from PIL import Image
from tests.helpers import recipe
from tests.studio import generate_recipe, png_bytes, studio_client
from tests.unit.test_jobs_video import make_clip, needs_ffmpeg
from tests.unit.test_steps_face_pose import REG, runner_with

from p11.jobs.runner import JobControl, Runner, gallery_ref
from p11.media.nsfw import REFUSED_LIKENESS, GuardRefused, GuardUnavailable, Verdict
from p11.outputs import metadata
from p11.recipe.compile import EngineGraph, compile
from p11.recipe.likeness import carries_likeness, recipe_carries_likeness
from p11.recipe.model import (
    FaceRestore,
    FaceSwap,
    FileRef,
    Generate,
    Inpaint,
    ModelRef,
    Pose,
    Reference,
    ReplaceBackground,
    Slot,
    Upscale,
)
from p11.recipe.presets import DEFAULT_IPADAPTER, DEFAULT_IPADAPTER_FACE

REF_SLOT = (Slot(name="ref", kind="image"),)


class ScriptedGuard:
    """Records every image it is shown; ``unsafe`` decides the verdict."""

    def __init__(self, unsafe: bool = False) -> None:
        self.unsafe = unsafe
        self.seen: list[tuple[int, int]] = []

    def verdict(self, image: Image.Image) -> Verdict:
        self.seen.append(image.size)
        return Verdict(self.unsafe, (("scripted", 1.0 if self.unsafe else 0.0),))


async def guarded(tmp_path, guard: ScriptedGuard) -> Runner:
    runner = await runner_with(tmp_path)
    await runner.engine.start()
    runner.faces.guard = lambda: guard  # type: ignore[method-assign]
    return runner


async def run(runner: Runner, r, bindings=None) -> list[int]:
    report = await runner.run(
        recipe=r,
        bindings=bindings or {},
        count=1,
        template=None,
        parent=None,
        control=JobControl(),
        publish=lambda *a: None,
        job_id="j",
        on_progress=lambda *a: None,
    )
    return report.image_ids


def reference(mode: str = "style", adapter: str | None = None):
    return recipe(
        Generate(prompt="a portrait", aspect="1:1-1024"),
        Reference(
            image_slot="ref",
            mode=mode,
            ipadapter=ModelRef(manifest_id=adapter) if adapter else None,
        ),
        slots=REF_SLOT,
        id="ref-test",
    )


# ---------------------------------------------------------------------------------------------
# The pure rule and the compiled flag


@pytest.mark.parametrize(
    ("mode", "adapter", "expected"),
    [
        ("style", None, False),
        ("style", DEFAULT_IPADAPTER, False),
        ("character", None, True),
        ("face", None, True),
        ("style", DEFAULT_IPADAPTER_FACE, True),  # the face adapter in "style" mode is a face
    ],
)
def test_which_reference_steps_carry_a_likeness(mode, adapter, expected) -> None:
    r = reference(mode, adapter)
    assert carries_likeness(r.steps[1]) is expected
    assert recipe_carries_likeness(r) is expected
    [g] = compile(r, {"ref": FileRef(ref="ref-1")}, REG, seed=1)
    assert isinstance(g, EngineGraph) and g.likeness is expected


def test_a_face_swap_carries_a_likeness_and_plain_generation_does_not() -> None:
    assert carries_likeness(FaceSwap(face_slot="face"))
    assert not recipe_carries_likeness(recipe(Generate(prompt="x")))


# ---------------------------------------------------------------------------------------------
# The runner


async def test_a_face_reference_output_is_checked_and_refused(tmp_path) -> None:
    runner = await guarded(tmp_path, ScriptedGuard(unsafe=True))
    ref = runner.inputs.add_image(png_bytes((64, 64)), "image")
    with pytest.raises(GuardRefused, match="face from a photo"):
        await run(runner, reference("face"), {"ref": FileRef(ref=ref.id)})
    assert not list(runner.outputs_root.rglob("*.png"))  # nothing was saved
    assert "nude or sexual" in REFUSED_LIKENESS


async def test_a_style_reference_stays_unfiltered(tmp_path) -> None:
    """A5: generation without a likeness is never shown to the guard."""
    guard = ScriptedGuard(unsafe=True)
    runner = await guarded(tmp_path, guard)
    ref = runner.inputs.add_image(png_bytes((64, 64)), "image")
    assert await run(runner, reference("style"), {"ref": FileRef(ref=ref.id)})
    assert guard.seen == []


async def test_steps_after_a_face_swap_are_checked_too(tmp_path) -> None:
    guard = ScriptedGuard()
    runner = await guarded(tmp_path, guard)
    target = runner.inputs.add_image(png_bytes((64, 64)), "image")
    face = runner.inputs.add_image(png_bytes((32, 32)), "image")
    r = recipe(
        FaceSwap(face_slot="face"),
        Upscale(scale=2.0),
        slots=(Slot(name="face", kind="face_image"),),
        source_image=FileRef(ref=target.id),
        id="swap-then-upscale",
    )
    ids = await run(runner, r, {"face": FileRef(ref=face.id)})
    # The swap's target and result, plus the upscale's output.
    assert len(guard.seen) >= 3
    record = metadata.read_sidecar(
        metadata.sidecar_path(runner.outputs_root / _path(runner, ids[-1]))
    )
    assert record.likeness


def _path(runner: Runner, image_id: int) -> str:
    entry = runner.gallery.get(image_id)
    assert entry is not None
    return entry.path


async def test_a_later_edit_of_a_likeness_picture_is_checked(tmp_path) -> None:
    guard = ScriptedGuard()
    runner = await guarded(tmp_path, guard)
    ref = runner.inputs.add_image(png_bytes((64, 64)), "image")
    [made] = await run(runner, reference("character"), {"ref": FileRef(ref=ref.id)})
    edit = recipe(Upscale(scale=2.0), source_image=FileRef(ref=gallery_ref(made)), id="edit")
    assert runner.inputs_carry_likeness(edit, {})
    guard.unsafe = True
    with pytest.raises(GuardRefused):
        await run(runner, edit)


async def test_an_edit_of_an_ordinary_picture_is_not(tmp_path) -> None:
    guard = ScriptedGuard(unsafe=True)
    runner = await guarded(tmp_path, guard)
    [made] = await run(runner, recipe(Generate(prompt="a fox", aspect="1:1-1024"), id="plain"))
    edit = recipe(Upscale(scale=2.0), source_image=FileRef(ref=gallery_ref(made)), id="edit")
    assert not runner.inputs_carry_likeness(edit, {})
    assert await run(runner, edit)
    assert guard.seen == []


async def test_a_face_reference_fails_closed_without_the_guard_models(tmp_path) -> None:
    runner = await runner_with(tmp_path)

    def missing():
        raise GuardUnavailable("Face swap and face reference need their image check models")

    runner.faces.guard = missing  # type: ignore[method-assign]
    ref = runner.inputs.add_image(png_bytes((64, 64)), "image")
    with pytest.raises(GuardUnavailable):
        runner.validate(reference("face"), {"ref": FileRef(ref=ref.id)})
    runner.validate(reference("style"), {"ref": FileRef(ref=ref.id)})  # style needs no guard


# ---------------------------------------------------------------------------------------------
# The gallery picker (Phase 17g, ADR-0046): every image input takes a `gallery/<id>` reference, so
# a picture from a likeness run stays guarded whichever control it is picked in.


def mask_ref(runner: Runner) -> FileRef:
    return FileRef(ref=runner.inputs.add_image(png_bytes((64, 64), "white"), "mask").id)


def plain_ref(runner: Runner) -> FileRef:
    return FileRef(ref=runner.inputs.add_image(png_bytes((64, 64)), "image").id)


def generate_photo(picked: FileRef, runner: Runner):
    return recipe(
        Generate(prompt="a portrait", aspect="1:1-1024", denoise=0.7),
        source_image=picked,
        id="pick",
    ), {}


def inpaint_source(picked: FileRef, runner: Runner):
    r = recipe(
        Inpaint(mask_slot="mask", prompt="a scarf"),
        slots=(Slot(name="mask", kind="mask"),),
        source_image=picked,
        id="pick",
    )
    return r, {"mask": mask_ref(runner)}


def background_subject(picked: FileRef, runner: Runner):
    return recipe(
        ReplaceBackground(background_colour="#336699"), source_image=picked, id="pick"
    ), {}


def background_photo(picked: FileRef, runner: Runner):
    r = recipe(
        ReplaceBackground(background_slot="bg"),
        slots=(Slot(name="bg", kind="background_image"),),
        source_image=plain_ref(runner),
        id="pick",
    )
    return r, {"bg": picked}


def face_picture(picked: FileRef, runner: Runner):
    r = recipe(
        FaceSwap(face_slot="face"),
        slots=(Slot(name="face", kind="face_image"),),
        source_image=picked,
        id="pick",
    )
    return r, {"face": plain_ref(runner)}


def face_photo(picked: FileRef, runner: Runner):
    r = recipe(
        FaceSwap(face_slot="face"),
        slots=(Slot(name="face", kind="face_image"),),
        source_image=plain_ref(runner),
        id="pick",
    )
    return r, {"face": picked}


def restore_picture(picked: FileRef, runner: Runner):
    return recipe(FaceRestore(), source_image=picked, id="pick"), {}


def pose_photo(picked: FileRef, runner: Runner):
    r = recipe(
        Generate(prompt="a portrait", aspect="1:1-1024"),
        Pose(pose_slot="pose"),
        slots=(Slot(name="pose", kind="image"),),
        id="pick",
    )
    return r, {"pose": picked}


def reference_image(picked: FileRef, runner: Runner):
    r = recipe(
        Generate(prompt="a portrait", aspect="1:1-1024"),
        Reference(image_slot="ref", mode="style"),
        slots=REF_SLOT,
        id="pick",
    )
    return r, {"ref": picked}


def template_slot(picked: FileRef, runner: Runner):
    r = recipe(
        Upscale(image_slot="photo", scale=2.0),
        slots=(Slot(name="photo", kind="image"),),
        id="pick",
    )
    return r, {"photo": picked}


CONTROLS = [
    generate_photo,
    inpaint_source,
    background_subject,
    background_photo,
    face_picture,
    face_photo,
    restore_picture,
    pose_photo,
    reference_image,
    template_slot,
]


@pytest.mark.parametrize("control", CONTROLS, ids=lambda c: c.__name__)
async def test_a_likeness_picture_stays_guarded_when_picked(tmp_path, control) -> None:
    guard = ScriptedGuard()
    runner = await guarded(tmp_path, guard)
    ref = plain_ref(runner)
    [made] = await run(runner, reference("character"), {"ref": ref})
    r, bindings = control(FileRef(ref=gallery_ref(made)), runner)
    assert runner.inputs_carry_likeness(r, bindings)
    runner.validate(r, bindings)  # the reference resolves through the control's own path
    guard.unsafe = True
    with pytest.raises(GuardRefused):
        await run(runner, r, bindings)
    assert len(list(runner.outputs_root.rglob("*.png"))) == 1  # only the picture it started from


async def test_a_restored_upload_showing_a_face_stays_guarded(tmp_path) -> None:
    """ADR-0038 for Restore faces: otherwise its gallery result is a clean copy of the upload."""
    guard = ScriptedGuard()
    runner = await guarded(tmp_path, guard)
    r = recipe(FaceRestore(), source_image=plain_ref(runner), id="restore")
    assert Runner.edited_uploads(r, {}) == [r.source_image]
    [made] = await run(runner, r)
    record = metadata.read_sidecar(metadata.sidecar_path(runner.outputs_root / _path(runner, made)))
    assert record.likeness
    assert guard.seen


def composite_body(picture: str, background: str | None) -> dict:
    return {
        "image": {"ref": picture},
        "background": {"ref": background} if background else None,
        "feather_px": 0,
    }


def test_the_background_preview_guards_a_likeness_picture(tmp_path) -> None:
    """The preview shows the composite Apply would save, so it passes the same guard."""
    with studio_client(tmp_path) as client:
        runner = client.studio.queue.runner
        guard = ScriptedGuard(unsafe=True)
        runner.faces.guard = lambda: guard  # type: ignore[method-assign]
        plain = client.post(
            "/api/uploads?kind=image", content=png_bytes((32, 24)), headers=client.auth
        ).json()["id"]
        ok = client.post(
            "/api/background/preview", json=composite_body(plain, plain), headers=client.auth
        )
        assert ok.status_code == 200 and guard.seen == []  # A5: no likeness, no check

        image_id = _likeness_image(client)
        for body in (
            composite_body(f"gallery/{image_id}", plain),
            composite_body(plain, f"gallery/{image_id}"),
        ):
            refused = client.post("/api/background/preview", json=body, headers=client.auth)
            assert refused.status_code == 422, refused.text
            assert "nude or sexual" in refused.json()["message"]


def _likeness_image(client) -> int:
    """A gallery image whose run record says it carries a likeness."""
    done = client.post(
        "/api/jobs",
        json={"recipe": generate_recipe(id="like")},
        headers=client.auth,
    ).json()
    image_id = client.wait_job(done["id"])["images"][0]
    path = client.get(f"/api/images/{image_id}/info", headers=client.auth).json()["path"]
    sidecar = metadata.sidecar_path(client.studio.queue.runner.outputs_root / path)
    record = metadata.read_sidecar(sidecar)
    sidecar.write_text(record.model_copy(update={"likeness": True}).to_json())
    return image_id


@needs_ffmpeg
def test_a_gallery_face_on_a_video_keeps_the_frame_guard(tmp_path) -> None:
    clip = tmp_path / "pink.mp4"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=magenta:s=160x120:d=1:r=10",
         "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )  # fmt: skip
    with studio_client(tmp_path) as client:
        guard = ScriptedGuard(unsafe=True)
        client.studio.queue.runner.faces.guard = lambda: guard  # type: ignore[method-assign]
        image_id = _likeness_image(client)
        vid = client.post(
            "/api/uploads?kind=video", content=clip.read_bytes(), headers=client.auth
        ).json()["id"]
        refused = client.post(
            "/api/video/jobs",
            json={"video": vid, "face": f"gallery/{image_id}", "quality": "fast"},
            headers=client.auth,
        )
        assert refused.status_code == 422, refused.text
        assert "nude or sexual" in refused.json()["message"]


@needs_ffmpeg
def test_a_gallery_face_swaps_into_a_clip_and_a_deleted_one_says_so(tmp_path) -> None:
    """Regression: a gallery face used to crash here, its index read in a worker thread."""
    clip = make_clip(tmp_path / "clip.mp4")
    with studio_client(tmp_path) as client:
        image_id = _likeness_image(client)
        vid = client.post(
            "/api/uploads?kind=video", content=clip.read_bytes(), headers=client.auth
        ).json()["id"]
        body = {"video": vid, "face": f"gallery/{image_id}", "quality": "fast"}
        job = client.post("/api/video/jobs", json=body, headers=client.auth)
        assert job.status_code == 201, job.text
        assert client.wait_job(job.json()["id"])["state"] == "done"

        client.delete(f"/api/images/{image_id}", headers=client.auth)
        gone = client.post("/api/video/jobs", json=body, headers=client.auth)
        assert "face photo is gone" in gone.json()["message"]


def test_a_picked_image_deleted_before_the_job_runs_gets_the_plain_message(tmp_path) -> None:
    with studio_client(tmp_path) as client:
        image_id = _likeness_image(client)
        client.delete(f"/api/images/{image_id}", headers=client.auth)
        r = recipe(Upscale(scale=2.0), source_image=FileRef(ref=f"gallery/{image_id}"), id="gone")
        job = client.post(
            "/api/jobs", json={"recipe": r.model_dump(mode="json")}, headers=client.auth
        )
        assert job.status_code >= 400
        assert "does not exist any more" in job.json()["message"]

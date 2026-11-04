"""S5 beyond the swap itself (Phase 16, ADR-0037): pictures that carry a person's likeness.

A face reference (IP-Adapter Plus Face) keeps a person recognisable in a generated picture, and an
edit of a face-swapped picture works on that person's face. Both are checked by the S5 guard like
the swap's own result: inside the run, for every later step, and for later jobs made from such a
gallery image. Uses a scripted guard (no real photos, S6).
"""

from __future__ import annotations

import pytest
from PIL import Image
from tests.helpers import recipe
from tests.studio import png_bytes
from tests.unit.test_steps_face_pose import REG, runner_with

from p11.jobs.runner import JobControl, Runner, gallery_ref
from p11.media.nsfw import REFUSED_LIKENESS, GuardRefused, GuardUnavailable, Verdict
from p11.outputs import metadata
from p11.recipe.compile import EngineGraph, compile
from p11.recipe.likeness import carries_likeness, recipe_carries_likeness
from p11.recipe.model import (
    FaceSwap,
    FileRef,
    Generate,
    ModelRef,
    Reference,
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

"""The ``face_swap`` and ``face_restore`` steps (Phase 12, ADR-0028): local work in ``p11.media``.

Both are ``LocalStep``s (ADR-0027): they run on the CPU inside P11 and never touch the engine, so
they cost no VRAM and their models are not ComfyUI custom nodes (S3). The S5 NSFW target guard runs
in the local step **before** anything else and again on the result (``p11.media.faces``); there is
no way for a recipe, a template or an API call to skip it.
"""

from __future__ import annotations

from ..compile import CompileContext, LocalStep, PlanItem, register_plan_step
from ..model import FaceRestore, FaceSwap
from ..presets import (
    DEFAULT_DETECTOR,
    DEFAULT_GUARD_CLASSIFIERS,
    DEFAULT_RECOGNIZER,
    DEFAULT_RESTORER,
    DEFAULT_SWAPPER,
)


def compile_face_swap(step: FaceSwap, ctx: CompileContext) -> list[PlanItem]:
    models = [DEFAULT_SWAPPER, DEFAULT_DETECTOR, DEFAULT_RECOGNIZER, *DEFAULT_GUARD_CLASSIFIERS]
    swapper = ctx.model(step.swapper_model, DEFAULT_SWAPPER, "faceswap")
    ctx.model(None, DEFAULT_DETECTOR, "facedetect")
    ctx.model(None, DEFAULT_RECOGNIZER, "facedetect")
    for mid in DEFAULT_GUARD_CLASSIFIERS:
        ctx.model(None, mid, "classifier")
    if step.restore and step.restore_visibility > 0:
        ctx.model(step.restore_model, DEFAULT_RESTORER, "facerestore")
        models.append(DEFAULT_RESTORER)

    inputs = [
        _bound(ctx, step.image_slot, "image"),
        _bound(ctx, step.face_slot, "face"),
    ]
    params = {
        "source_face_index": step.source_face_index,
        "target_face_index": step.target_face_index,
        "blend": step.blend,
        "restore": step.restore,
        "restore_visibility": step.restore_visibility,
        "swapper_model": swapper.manifest_id,
        "restore_model": (
            ctx.model(step.restore_model, DEFAULT_RESTORER, "facerestore").manifest_id
            if step.restore and step.restore_visibility > 0
            else None
        ),
    }
    return [
        LocalStep(
            step_index=ctx.step_index,
            step_type="face_swap",
            op="face_swap",
            params=params,
            inputs=tuple(inputs),
            models=tuple(dict.fromkeys(m for m in models)),
        )
    ]


def compile_face_restore(step: FaceRestore, ctx: CompileContext) -> list[PlanItem]:
    restore = ctx.model(step.restore_model, DEFAULT_RESTORER, "facerestore")
    ctx.model(None, DEFAULT_DETECTOR, "facedetect")
    inputs = [_bound(ctx, step.image_slot, "image")]
    params = {
        "face_index": step.face_index,
        "visibility": step.visibility,
        "restore_model": restore.manifest_id,
    }
    return [
        LocalStep(
            step_index=ctx.step_index,
            step_type="face_restore",
            op="face_restore",
            params=params,
            inputs=tuple(inputs),
            models=(restore.manifest_id, DEFAULT_DETECTOR),
        )
    ]


def _bound(ctx: CompileContext, slot: str | None, placeholder: str):  # type: ignore[no-untyped-def]
    from dataclasses import replace

    return replace(ctx.resolve_input(slot), placeholder=placeholder)


register_plan_step("face_swap", compile_face_swap)
register_plan_step("face_restore", compile_face_restore)

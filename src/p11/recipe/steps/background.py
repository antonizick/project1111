"""The ``replace_background`` step (Phase 11, ADR-0027): subject onto a new background.

Segmentation and compositing run in P11 on the CPU as a ``LocalStep`` (``p11.media.composite``):
find the subject (or take the stored mask), fit the background photo or colour, match colours,
clean the edge and blend with a feathered mask. With ``relight`` and a photo background the step
also gets an engine tail: the Phase 10 inpaint graph at low denoise over the seam band the local
step returns as its ``mask`` output, pasted back exactly (``p11.media.inpaint`` crop-and-stitch).

Core ComfyUI nodes only (S3); names as read from ComfyUI v0.43.0 (``426f5ee``) for Phase 10
(``steps/inpaint.py``), checked again 2026-11-03 07:35 CST.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import replace

from ..compile import (
    CompileContext,
    CompileError,
    EngineGraph,
    GraphBuilder,
    LocalStep,
    MaskPrep,
    PlanItem,
    _style,
    graph_from,
    register_plan_step,
)
from ..model import ReplaceBackground
from ..presets import (
    DEFAULT_MODEL,
    DEFAULT_SEGMENTER,
    INPAINT_MAX_PIXELS,
    INPAINT_MAX_UPSCALE,
    INPAINT_WORK_PIXELS,
)

#: Softening of the seam band around the harmonize crop (the band itself is blurred locally).
SEAM_GROW_PX = 8
SEAM_BLUR_PX = 8
SEAM_PADDING_PX = 64


def _inline_mask(step: ReplaceBackground, ctx: CompileContext) -> bytes | None:
    if step.mask_png is None:
        return None
    try:
        data = base64.b64decode(step.mask_png, validate=True)
    except (binascii.Error, ValueError):
        raise CompileError(f"{ctx.where}: the saved mask is damaged; paint a new one.") from None
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise CompileError(f"{ctx.where}: the saved mask is not a PNG; paint a new one.")
    return data


def compile_replace_background(step: ReplaceBackground, ctx: CompileContext) -> list[PlanItem]:
    seg_id: str | None = None
    if step.mask_mode == "auto":
        seg = ctx.model(step.segmentation_model, DEFAULT_SEGMENTER, "segmentation")
        seg_id = seg.manifest_id

    inputs = [replace(ctx.resolve_input(step.image_slot), placeholder="image")]
    if step.background_slot is not None:
        inputs.append(replace(ctx.resolve_input(step.background_slot), placeholder="background"))
    if step.mask_mode == "manual":
        inputs.append(
            replace(ctx.mask_input(step.mask_slot, _inline_mask(step, ctx)), placeholder="mask")
        )

    params = {
        "colour_match": step.colour_match,
        "colour_match_strength": step.colour_match_strength,
        "feather_px": step.feather_px,
        "fit": step.fit,
        "background_x": step.background_x,
        "background_y": step.background_y,
        "subject_scale": step.subject_scale,
        "subject_x": step.subject_x,
        "subject_y": step.subject_y,
        "shadow": step.shadow,
        "background_colour": step.background_colour,
        "segmentation_model": seg_id,
    }
    local = LocalStep(
        step_index=ctx.step_index,
        step_type="replace_background",
        op="replace_background",
        params=params,
        inputs=tuple(inputs),
        models=(seg_id,) if seg_id else (),
    )

    # A flat colour or transparency has no light to match: no engine pass.
    if not step.relight or step.background_slot is None:
        return [local]
    return [local, _harmonize(step, ctx)]


def _harmonize(step: ReplaceBackground, ctx: CompileContext) -> EngineGraph:
    """The engine tail: a low-denoise inpaint pass over the seam band (``p11:local:mask``)."""
    gen = ctx.last_generate
    style = _style(gen.style, ctx) if gen else None
    default_ckpt = (gen.model.manifest_id if gen and gen.model else None) or (
        style.model if style else DEFAULT_MODEL
    )
    ckpt = ctx.model(None, default_ckpt, "checkpoint")
    d = ckpt.defaults
    if d is None:
        raise CompileError(f"{ctx.where}: model {ckpt.manifest_id!r} has no sampler defaults.")
    g = GraphBuilder()
    g.use_model(ckpt)
    loader = g.node("CheckpointLoaderSimple", ckpt_name=ckpt.filename)
    model, clip, vae = [loader[0], 0], [loader[0], 1], [loader[0], 2]
    if ckpt.vae:
        vae_info = ctx.model(None, ckpt.vae, "vae")
        g.use_model(vae_info)
        vae = g.node("VAELoader", vae_name=vae_info.filename)
    if d.clip_skip > 1:
        clip = g.node("CLIPSetLastLayer", clip=clip, stop_at_clip_layer=-d.clip_skip)

    prompt = ctx.text(step.prompt) or (ctx.text(gen.prompt) if gen else "")
    negative = ctx.text(step.negative) or (ctx.text(gen.negative) if gen else "")
    pos_text = style.positive(prompt) if style else prompt.strip()
    neg_text = style.negative_for(negative) if style else negative.strip()
    positive = g.node("CLIPTextEncode", text=pos_text, clip=clip)
    negative_c = g.node("CLIPTextEncode", text=neg_text, clip=clip)

    image = ctx.load_local(g, "image")
    mask = ctx.load_local(g, "mask", mask=True)
    cond = g.node(
        "InpaintModelConditioning",
        positive=positive,
        negative=negative_c,
        vae=vae,
        pixels=image,
        mask=mask,
        noise_mask=True,
    )
    sampled = g.node(
        "KSampler",
        "harmonize",
        model=model,
        seed=ctx.seed,
        steps=max(1, d.steps // 2),
        cfg=d.cfg,
        sampler_name=d.sampler_name,
        scheduler=d.scheduler,
        positive=[cond[0], 0],
        negative=[cond[0], 1],
        latent_image=[cond[0], 2],
        denoise=step.relight_denoise,
    )
    decoded = g.node("VAEDecode", samples=sampled, vae=vae)
    g.prep = MaskPrep(
        image="p11:local:image",
        mask="p11:local:mask",
        grow_px=SEAM_GROW_PX,
        blur_px=SEAM_BLUR_PX,
        crop=True,
        padding_px=SEAM_PADDING_PX,
        work_pixels=INPAINT_WORK_PIXELS,
        max_upscale=INPAINT_MAX_UPSCALE,
        max_pixels=INPAINT_MAX_PIXELS,
    )
    out = g.node(
        "ImageCompositeMasked",
        destination=image,
        source=decoded,
        x=0,
        y=0,
        resize_source=False,
        mask=mask,
    )
    return graph_from(g, ctx, out)


register_plan_step("replace_background", compile_replace_background)

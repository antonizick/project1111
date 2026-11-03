"""The ``inpaint`` step (Phase 10, ADR-0025): repaint the masked part of an image.

Core ComfyUI nodes only (S3). Class and input names were read from the pinned ComfyUI v0.43.0
(``426f5ee``) on 2026-11-03 04:50 CST: ``nodes.py`` (``LoadImageMask`` with ``channel``,
``InpaintModelConditioning`` → positive, negative, latent, with ``noise_mask``) and
``comfy_extras/nodes_mask.py`` (``ImageCompositeMasked`` with ``destination, source, x, y,
resize_source, mask``).

The graph works on the image and mask the job runner prepared (``MaskPrep``; ``p11.media.inpaint``):
the mask arrives grown and blurred, and with ``crop`` both arrive as a padded box around the mask
scaled to the model's working size. Sampling is limited to the mask (noise mask), then the decoded
result is blended over the input with the same soft mask; the runner pastes it back at full size.
"""

from __future__ import annotations

import base64
import binascii

from ..compile import (
    CompileContext,
    CompileError,
    GraphBuilder,
    MaskPrep,
    Ref,
    _sampler,
    _style,
    register_step,
)
from ..model import Inpaint
from ..presets import (
    DEFAULT_MODEL,
    INPAINT_MAX_PIXELS,
    INPAINT_MAX_UPSCALE,
    INPAINT_PRESETS,
    INPAINT_WORK_PIXELS,
)


def denoise_of(step: Inpaint) -> float:
    """The strength the step samples with: the preset's tuned value, else ``denoise``."""
    if step.denoise_preset is not None:
        return INPAINT_PRESETS[step.denoise_preset]
    return step.denoise


def _inline_mask(step: Inpaint, ctx: CompileContext) -> bytes | None:
    if step.mask_png is None:
        return None
    try:
        data = base64.b64decode(step.mask_png, validate=True)
    except (binascii.Error, ValueError):
        raise CompileError(f"{ctx.where}: the saved mask is damaged; paint a new one.") from None
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise CompileError(f"{ctx.where}: the saved mask is not a PNG; paint a new one.")
    return data


def compile_inpaint(step: Inpaint, ctx: CompileContext, g: GraphBuilder) -> Ref:
    gen = ctx.last_generate
    style = _style(gen.style, ctx) if gen else None
    default_ckpt = (gen.model.manifest_id if gen and gen.model else None) or (
        style.model if style else DEFAULT_MODEL
    )
    ckpt = ctx.model(step.model, default_ckpt, "checkpoint")
    sampler, scheduler, steps, cfg, clip_skip = _sampler(step, ckpt, ctx)

    g.use_model(ckpt)
    loader = g.node("CheckpointLoaderSimple", ckpt_name=ckpt.filename)
    model: Ref = [loader[0], 0]
    clip: Ref = [loader[0], 1]
    vae: Ref = [loader[0], 2]
    if ckpt.vae:
        vae_info = ctx.model(None, ckpt.vae, "vae")
        g.use_model(vae_info)
        vae = g.node("VAELoader", vae_name=vae_info.filename)
    if clip_skip > 1:
        clip = g.node("CLIPSetLastLayer", clip=clip, stop_at_clip_layer=-clip_skip)

    prompt = ctx.text(step.prompt) or (ctx.text(gen.prompt) if gen else "")
    negative = ctx.text(step.negative)
    pos_text = style.positive(prompt) if style else prompt.strip()
    neg_text = style.negative_for(negative) if style else negative.strip()
    positive = g.node("CLIPTextEncode", text=pos_text, clip=clip)
    negative_c = g.node("CLIPTextEncode", text=neg_text, clip=clip)

    image = ctx.load_image(g, step.image_slot)
    mask = ctx.load_mask(g, step.mask_slot, _inline_mask(step, ctx))
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
        "inpaint",
        model=model,
        seed=ctx.seed,
        steps=steps,
        cfg=cfg,
        sampler_name=sampler,
        scheduler=scheduler,
        positive=[cond[0], 0],
        negative=[cond[0], 1],
        latent_image=[cond[0], 2],
        denoise=denoise_of(step),
    )
    decoded = g.node("VAEDecode", samples=sampled, vae=vae)
    placeholders = {i.node_id: i.placeholder for i in g.inputs}
    g.prep = MaskPrep(
        image=placeholders[image[0]],
        mask=placeholders[mask[0]],
        grow_px=step.grow_mask_px,
        blur_px=step.mask_blur_px,
        crop=step.crop,
        padding_px=step.padding_px,
        work_pixels=INPAINT_WORK_PIXELS,
        max_upscale=INPAINT_MAX_UPSCALE,
        max_pixels=INPAINT_MAX_PIXELS,
    )
    return g.node(
        "ImageCompositeMasked",
        destination=image,
        source=decoded,
        x=0,
        y=0,
        resize_source=False,
        mask=mask,
    )


register_step("inpaint", compile_inpaint)

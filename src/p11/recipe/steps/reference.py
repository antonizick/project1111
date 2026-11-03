"""The ``reference`` modifier (Phase 12, ADR-0031): a style or character image in the generation.

The reference image is encoded by ComfyUI's core ``CLIPVisionLoader`` + ``CLIPVisionEncode`` and
applied with **P11's own** ``P11IPAdapterLoader`` + ``P11IPAdapterApply`` (the ``p11_ipadapter``
node pack in ``engine/custom_nodes/``, the only pack the engine may load, S3). Nothing
else in P11 may talk to the engine's IP-Adapter support, because there is none in ComfyUI v0.43.0.

``mode`` picks the checkpoint: ``style`` uses IP-Adapter Plus (composition and palette),
``character``/``face`` use IP-Adapter Plus Face (the person). Node inputs were read from the pack's
own source and ComfyUI v0.43.0 ``nodes.py`` on 2026-11-03 10:25 CST.
"""

from __future__ import annotations

from dataclasses import replace

from ..compile import CompileContext, Conditioning, GraphBuilder, register_modifier
from ..model import Reference
from ..presets import DEFAULT_CLIPVISION, DEFAULT_IPADAPTER, DEFAULT_IPADAPTER_FACE


def compile_reference(
    step: Reference, ctx: CompileContext, g: GraphBuilder, cond: Conditioning
) -> Conditioning:
    default = DEFAULT_IPADAPTER_FACE if step.mode in ("character", "face") else DEFAULT_IPADAPTER
    adapter = ctx.model(step.ipadapter, default, "ipadapter")
    encoder = ctx.model(None, DEFAULT_CLIPVISION, "clipvision")
    g.use_model(adapter)
    g.use_model(encoder)

    loader = g.node("P11IPAdapterLoader", ipadapter_file=adapter.filename)
    clip = g.node("CLIPVisionLoader", clip_name=encoder.filename)
    image = ctx.load_image(g, step.image_slot)
    g.inputs[-1] = replace(g.inputs[-1], transform="reference")
    embeds = g.node("CLIPVisionEncode", clip_vision=clip, image=image, crop="none")
    applied = g.node(
        "P11IPAdapterApply",
        model=cond.model,
        ipadapter=loader,
        clip_vision_output=embeds,
        weight=step.weight,
        start=step.start,
        end=step.end,
    )
    return replace(cond, model=[applied[0], 0])


register_modifier("reference", compile_reference)

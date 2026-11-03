"""The ``text_overlay`` step (Phase 14, ADR-0035): exact text on a logo, in P11, not the engine.

Compiles to a tail-less ``LocalStep`` (ADR-0027). ``p11.media.text`` draws it with a bundled font at
full resolution; the runner's save path then writes, sidecars and indexes it like any other step.
With ``also_prompt_model`` the step compiles to nothing: the user chose to let the model try the
text, so the generated image is saved as it is.
"""

from __future__ import annotations

from dataclasses import replace

from ..compile import CompileContext, LocalStep, PlanItem, register_plan_step
from ..model import TextOverlay


def compile_text_overlay(step: TextOverlay, ctx: CompileContext) -> list[PlanItem]:
    if step.also_prompt_model:
        return []
    text = ctx.text(step.text)
    if not text.strip():
        # An optional text slot left empty means "no text": skip the step, save the image as is.
        return []
    image = replace(ctx.resolve_input(None), placeholder="image")
    params = {
        "text": text,
        "font": step.font,
        "weight": step.weight,
        "size_pct": step.size_pct,
        "colour": step.colour,
        "colour2": step.colour2,
        "align": step.align,
        "position": step.position,
        "x": step.x,
        "y": step.y,
        "margin_pct": step.margin_pct,
        "letter_spacing": step.letter_spacing,
        "stroke_px": step.stroke_px,
        "stroke_colour": step.stroke_colour,
        "shadow": step.shadow,
    }
    return [
        LocalStep(
            step_index=ctx.step_index,
            step_type="text_overlay",
            op="text_overlay",
            params=params,
            inputs=(image,),
        )
    ]


register_plan_step("text_overlay", compile_text_overlay)

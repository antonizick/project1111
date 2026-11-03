"""The ``pose`` modifier (Phase 12, ADR-0030): the generation follows a pose, depth or line map.

``pose`` conditions the ``generate`` step it follows: the pose slot's image is turned into a control
map in P11 (``GraphInput.transform``): ``pose`` reads a body skeleton out of a photo or takes the
editor's drawing, ``depth`` and ``canny`` compute their maps. One ControlNet Union applies it.
The ControlNet is the engine's own ``ControlNetLoader`` + ``SetUnionControlNetType`` +
``ControlNetApplyAdvanced`` (core nodes at the pinned ComfyUI v0.43.0, checked 2026-11-03 10:25
CST), so no custom node is needed for controls.

Node names and inputs were read from ComfyUI v0.43.0 ``nodes.py`` (``ControlNetApplyAdvanced``:
positive, negative, control_net, image, strength, start_percent, end_percent) and
``comfy_extras/nodes_controlnet.py`` (``SetUnionControlNetType``: control_net, type) on
2026-11-03 10:25 CST.
"""

from __future__ import annotations

from dataclasses import replace

from ..compile import CompileContext, CompileError, Conditioning, GraphBuilder, register_modifier
from ..model import Pose
from ..presets import DEFAULT_CONTROLNET

#: ``Pose.control`` -> the union ControlNet's type and the runner's preprocessor.
CONTROL_TYPES: dict[str, tuple[str, str]] = {
    "openpose": ("openpose", "pose"),
    "depth": ("depth", "depth"),
    "canny": ("canny/lineart/anime_lineart/mlsd", "canny"),
}


def compile_pose(
    step: Pose, ctx: CompileContext, g: GraphBuilder, cond: Conditioning
) -> Conditioning:
    if step.control not in CONTROL_TYPES:
        raise CompileError(f"{ctx.where}: unknown control {step.control!r}.")
    union_type, transform = CONTROL_TYPES[step.control]
    info = ctx.model(step.controlnet, DEFAULT_CONTROLNET, "controlnet")
    g.use_model(info)
    loader = g.node("ControlNetLoader", control_net_name=info.filename)
    control = g.node("SetUnionControlNetType", control_net=loader, type=union_type)
    image = ctx.load_image(g, step.pose_slot)
    if step.preprocess:
        g.inputs[-1] = replace(g.inputs[-1], transform=transform)
    applied = g.node(
        "ControlNetApplyAdvanced",
        positive=cond.positive,
        negative=cond.negative,
        control_net=control,
        image=image,
        strength=step.strength,
        start_percent=step.start,
        end_percent=step.end,
    )
    return replace(cond, positive=[applied[0], 0], negative=[applied[0], 1])


register_modifier("pose", compile_pose)

"""Pure recipe → ComfyUI API-graph compiler (spec R6, ADR-0007).

``compile(recipe, bindings, registry)`` returns one ``EngineGraph`` per graph-producing step.
Graphs use core ComfyUI nodes only; class and input names were read from ComfyUI v0.43.0
(``426f5ee``, the commit pinned in ``engine/engine.lock.toml``): ``nodes.py`` and
``comfy_extras/nodes_upscale_model.py``, checked 2026-11-02 18:20 CST.

Extension point: later phases call ``register_step("inpaint", fn)`` for a step that produces a
graph, or ``register_modifier("pose", fn)`` for a step that conditions the preceding ``generate``.
Images flow between graphs through ``GraphInput`` placeholders: a ``LoadImage`` node whose ``image``
is ``p11:slot:<name>``, ``p11:step:<index>`` or ``p11:source``; the job runner (Phase 05/07) uploads
the file and substitutes the engine's file name before queueing.

Deterministic: the same recipe, bindings, registry and seed give byte-identical ``to_json()``.
"""

from __future__ import annotations

import json
import math
import random
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from .model import (
    MAX_SEED,
    PLACEHOLDER,
    FileRef,
    FixedSeed,
    Generate,
    IncrementSeed,
    Inpaint,
    ModelRef,
    RandomSeed,
    Recipe,
    SeedStrategy,
    Step,
    Upscale,
)
from .presets import (
    ASPECTS,
    BUCKETS,
    DEFAULT_MODEL,
    DEFAULT_UPSCALER,
    HIRES_DENOISE,
    IMG2IMG_DEFAULT_PRESET,
    IMG2IMG_MAX_PIXELS,
    IMG2IMG_MIN_STEPS,
    IMG2IMG_MIN_UPSCALE,
    IMG2IMG_PRESETS,
    STYLES,
    VAE_OVERLAP,
    VAE_TILE,
    AspectPreset,
    StylePreset,
)
from .registry import Family, ModelInfo, ModelKind, ModelRegistry, UnknownModelError

# ComfyUI v0.43.0 comfy/samplers.py: KSAMPLER_NAMES + ["ddim", "uni_pc", "uni_pc_bh2"] and
# SCHEDULER_HANDLERS. Checked at compile time, not in the schema, so an engine bump never
# invalidates stored recipes.
_SAMPLER_NAMES = """euler euler_cfg_pp euler_ancestral euler_ancestral_cfg_pp heun heunpp2
exp_heun_2_x0 exp_heun_2_x0_sde dpm_2 dpm_2_ancestral lms dpm_fast dpm_adaptive dpmpp_2s_ancestral
dpmpp_2s_ancestral_cfg_pp dpmpp_sde dpmpp_sde_gpu dpmpp_2m dpmpp_2m_cfg_pp dpmpp_2m_sde
dpmpp_2m_sde_gpu dpmpp_2m_sde_heun dpmpp_2m_sde_heun_gpu dpmpp_3m_sde dpmpp_3m_sde_gpu ddpm lcm
ipndm
ipndm_v deis cfgpp_ud10_ab res_multistep res_multistep_cfg_pp res_multistep_ancestral
res_multistep_ancestral_cfg_pp gradient_estimation gradient_estimation_cfg_pp er_sde seeds_2 seeds_3
sa_solver sa_solver_pece ddim uni_pc uni_pc_bh2"""
_SCHEDULER_NAMES = (
    "simple sgm_uniform karras exponential ddim_uniform beta normal linear_quadratic \
kl_optimal"
)
SAMPLERS: frozenset[str] = frozenset(_SAMPLER_NAMES.split())
SCHEDULERS: frozenset[str] = frozenset(_SCHEDULER_NAMES.split())

_EMPTY_PHRASES = re.compile(r"\s*,(?:\s*,)+\s*")

Bindings = Mapping[str, str | FileRef]
#: Pixel size of input files by ``FileRef.ref``, read by the job runner (the compiler stays pure).
ImageSizes = Mapping[str, tuple[int, int]]
Ref = list[Any]  # [node_id, output_index], ComfyUI's link format


class CompileError(ValueError):
    """The recipe cannot be compiled; the message is plain English and names what to fix."""


class SlotBindingError(CompileError):
    def __init__(self, slot: str, message: str) -> None:
        super().__init__(message)
        self.slot = slot


class UnsupportedStepError(CompileError):
    pass


# ---------------------------------------------------------------------------------------------
# Output types


@dataclass(frozen=True)
class GraphInput:
    """A ``LoadImage`` node the job runner must feed before queueing the graph.

    ``inline`` inputs carry their bytes (a template's fixed inpaint mask); ``local`` inputs are fed
    from the same step's local output (``p11:local:<name>``); the others name a file.
    """

    node_id: str
    source: Literal["slot", "step", "source", "inline", "local"]
    placeholder: str
    slot: str | None = None
    step: int | None = None
    file: FileRef | None = None
    data: bytes | None = None
    #: How the runner uploads it to the engine.
    kind: Literal["image", "mask"] = "image"
    #: Preprocessing the runner applies to these bytes before uploading (Phase 12 controls):
    #: ``pose`` (photo -> OpenPose skeleton image), ``depth`` or ``canny``. ``None``: upload as is.
    transform: str | None = None


@dataclass(frozen=True)
class MaskPrep:
    """Work the job runner does around an inpaint graph (``p11.media.inpaint``, ADR-0025).

    Before queueing: grow and blur the mask at full resolution and, with ``crop``, cut a padded box
    around it and scale it to the working size. After the run: scale the result back and blend it
    into the original with the soft mask, so pixels outside the blend band stay as they were.
    """

    image: str
    mask: str
    grow_px: int
    blur_px: int
    crop: bool
    padding_px: int
    work_pixels: int
    max_upscale: float
    max_pixels: int


@dataclass(frozen=True)
class EngineGraph:
    step_index: int
    step_type: str
    nodes: dict[str, dict[str, Any]]
    output_node: str
    inputs: tuple[GraphInput, ...]
    models: tuple[str, ...]
    seed: int
    #: Expected output size, when the compiler knows it (it does not for scale-by upscales).
    size: tuple[int, int] | None
    #: Mask preparation and paste-back the runner does around this graph (inpaint steps).
    prep: MaskPrep | None = None
    #: A modifier carried a person's likeness into this graph (``p11.recipe.likeness``, S5): the
    #: runner checks its output with the guard.
    likeness: bool = False

    def to_json(self) -> bytes:
        """Canonical API-format JSON: sorted keys, no whitespace, UTF-8."""
        return json.dumps(
            self.nodes, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()


@dataclass(frozen=True)
class LocalStep:
    """Work the job runner does in P11 instead of on the engine (ADR-0027).

    ``replace_background`` segments and composites on the CPU (``p11.media.composite``) and only
    its optional harmonize pass is an engine graph; ``text_overlay`` (Phase 14) is local only.
    The runner resolves ``inputs`` exactly like graph inputs, runs the operation named by ``op``
    with the pure ``params``, and keeps its named byte outputs (``image``, ``mask``) for the
    ``engine`` tail and for the save path. A step compiles to one item, or to a local step plus
    its engine tail.
    """

    step_index: int
    step_type: str
    op: str
    params: Mapping[str, Any]
    inputs: tuple[GraphInput, ...]
    models: tuple[str, ...] = ()
    size: tuple[int, int] | None = None
    #: Engine pass run on the local outputs (``p11:local:…`` inputs), e.g. the harmonize pass.
    engine: EngineGraph | None = None


PlanItem = EngineGraph | LocalStep


# ---------------------------------------------------------------------------------------------
# Graph building


class GraphBuilder:
    """Appends nodes with sequential string IDs ("1", "2", …) in call order."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.inputs: list[GraphInput] = []
        self.models: list[str] = []
        self.size: tuple[int, int] | None = None
        self.prep: MaskPrep | None = None
        self.likeness = False

    def node(self, class_type: str, title: str | None = None, **inputs: Any) -> Ref:
        nid = str(len(self.nodes) + 1)
        entry: dict[str, Any] = {"class_type": class_type, "inputs": inputs}
        if title:
            entry["_meta"] = {"title": title}
        self.nodes[nid] = entry
        return [nid, 0]

    def use_model(self, info: ModelInfo) -> None:
        if info.manifest_id not in self.models:
            self.models.append(info.manifest_id)


@dataclass(frozen=True)
class Conditioning:
    """What a modifier may change in a ``generate`` graph."""

    model: Ref
    clip: Ref
    vae: Ref
    positive: Ref
    negative: Ref
    family: str


@dataclass(frozen=True)
class CompileContext:
    recipe: Recipe
    bindings: Mapping[str, str | FileRef]
    registry: ModelRegistry
    seed: int
    step_index: int
    #: Modifier steps (pose, reference) that follow this step.
    modifiers: tuple[Step, ...] = ()
    #: Index of the graph-producing step before this one, or ``None`` if this is the first.
    previous_step: int | None = None
    #: The last ``generate`` step before this one, for defaults (upscale's refinement model).
    last_generate: Generate | None = None
    #: Known pixel sizes of input files (``ImageSizes``), for steps that size their graph by them.
    image_sizes: ImageSizes = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def where(self) -> str:
        step = self.recipe.steps[self.step_index]
        return f"Step {self.step_index + 1} ({step.type})"

    def text(self, value: str) -> str:
        """Substitute ``{{slot}}`` placeholders with bound text (empty for an unbound optional)."""

        def sub(m: Any) -> str:
            bound = self.bindings.get(m.group(1), "")
            return bound if isinstance(bound, str) else ""

        if not PLACEHOLDER.search(value):
            return value
        # An empty optional slot must not leave ", ," or a dangling comma behind.
        filled = _EMPTY_PHRASES.sub(", ", PLACEHOLDER.sub(sub, value))
        return filled.strip().strip(",").strip()

    def model(self, ref: ModelRef | None, default: str, kind: ModelKind) -> ModelInfo:
        manifest_id = ref.manifest_id if ref else default
        try:
            info = self.registry.get(manifest_id)
        except UnknownModelError as exc:
            raise CompileError(f"{self.where}: {exc}") from None
        if info.kind != kind:
            raise CompileError(
                f"{self.where}: model {manifest_id!r} is a {info.kind}, not a {kind}."
            )
        if ref and ref.sha256 and info.sha256 and ref.sha256 != info.sha256:
            raise CompileError(
                f"{self.where}: model {manifest_id!r} on disk is not the version this recipe was "
                "made with (hash differs). Re-download it or pick another model."
            )
        return info

    def resolve_input(self, slot: str | None) -> GraphInput:
        """Where an image comes from (no node): ``slot``, the previous step, or the source."""
        if slot is not None:
            bound = self.bindings.get(slot)
            if not isinstance(bound, FileRef):
                raise SlotBindingError(slot, f"{self.where} needs an image for {slot!r}.")
            kinds = {s.name: s.kind for s in self.recipe.slots}
            kind: Literal["image", "mask"] = "mask" if kinds.get(slot) == "mask" else "image"
            return GraphInput("", "slot", f"p11:slot:{slot}", slot=slot, file=bound, kind=kind)
        if self.previous_step is not None:
            return GraphInput("", "step", f"p11:step:{self.previous_step}", step=self.previous_step)
        if self.recipe.source_image is not None:
            return GraphInput("", "source", "p11:source", file=self.recipe.source_image)
        raise CompileError(f"{self.where} needs an input image, but none comes before it.")

    def load_image(self, g: GraphBuilder, slot: str | None) -> Ref:
        """A ``LoadImage`` fed from ``slot``, else the previous step's output, else the source."""
        inp = self.resolve_input(slot)
        ref = g.node("LoadImage", image=inp.placeholder)
        g.inputs.append(replace(inp, node_id=ref[0]))
        return ref

    def mask_input(self, slot: str | None, inline: bytes | None = None) -> GraphInput:
        """Where a mask comes from (no node): ``inline`` bytes or the ``slot``'s file."""
        if inline is not None:
            return GraphInput(
                "", "inline", f"p11:inline:{self.step_index}", data=inline, kind="mask"
            )
        if slot is None:
            raise CompileError(f"{self.where} needs a mask.")
        bound = self.bindings.get(slot)
        if not isinstance(bound, FileRef):
            raise SlotBindingError(slot, f"{self.where}: paint or upload a mask for {slot!r}.")
        return GraphInput("", "slot", f"p11:slot:{slot}", slot=slot, file=bound, kind="mask")

    def load_mask(self, g: GraphBuilder, slot: str | None, inline: bytes | None = None) -> Ref:
        """A ``LoadImageMask`` (red channel of a greyscale PNG) fed from ``slot`` or ``inline``."""
        inp = self.mask_input(slot, inline)
        ref = g.node("LoadImageMask", image=inp.placeholder, channel="red")
        g.inputs.append(replace(inp, node_id=ref[0]))
        return ref

    def load_local(self, g: GraphBuilder, name: str, *, mask: bool = False) -> Ref:
        """A ``LoadImage``/``LoadImageMask`` fed from this step's local output ``name``."""
        placeholder = f"p11:local:{name}"
        inp = GraphInput("", "local", placeholder, kind="mask" if mask else "image")
        if mask:
            ref = g.node("LoadImageMask", image=placeholder, channel="red")
        else:
            ref = g.node("LoadImage", image=placeholder)
        g.inputs.append(replace(inp, node_id=ref[0]))
        return ref


StepCompiler = Callable[[Any, CompileContext, GraphBuilder], Ref]
#: A step that is not one engine graph: local work (``p11.media``) and optionally an engine tail.
PlanCompiler = Callable[[Any, CompileContext], list[PlanItem]]
ModifierCompiler = Callable[[Any, CompileContext, GraphBuilder, Conditioning], Conditioning]

_STEP_COMPILERS: dict[str, StepCompiler] = {}
_PLAN_COMPILERS: dict[str, PlanCompiler] = {}
_MODIFIERS: dict[str, ModifierCompiler] = {}
_NOT_YET: dict[str, str] = {}


def register_step(step_type: str, fn: StepCompiler, *, replace: bool = False) -> None:
    """Register the compiler for a graph-producing step type. ``fn`` returns the IMAGE output."""
    if step_type in _STEP_COMPILERS and not replace:
        raise ValueError(f"a compiler for {step_type!r} is already registered")
    _STEP_COMPILERS[step_type] = fn


def register_plan_step(step_type: str, fn: PlanCompiler, *, replace: bool = False) -> None:
    """Register a compiler returning plan items (local steps / graphs), not one graph."""
    if step_type in _PLAN_COMPILERS and not replace:
        raise ValueError(f"a compiler for {step_type!r} is already registered")
    _PLAN_COMPILERS[step_type] = fn


def register_modifier(step_type: str, fn: ModifierCompiler, *, replace: bool = False) -> None:
    """Register a modifier (pose, reference) that rewrites a ``generate`` graph's conditioning."""
    if step_type in _MODIFIERS and not replace:
        raise ValueError(f"a modifier for {step_type!r} is already registered")
    _MODIFIERS[step_type] = fn


def unregister(step_type: str) -> None:
    _STEP_COMPILERS.pop(step_type, None)
    _PLAN_COMPILERS.pop(step_type, None)
    _MODIFIERS.pop(step_type, None)


# ---------------------------------------------------------------------------------------------
# Seeds and bindings


def resolve_seed(
    strategy: SeedStrategy, run_index: int = 0, rng: random.Random | None = None
) -> int:
    """The seed for run ``run_index``; a random strategy draws from ``rng`` (required for it)."""
    if isinstance(strategy, FixedSeed):
        return strategy.value
    if isinstance(strategy, IncrementSeed):
        return (strategy.start + run_index) % (MAX_SEED + 1)
    assert isinstance(strategy, RandomSeed)
    if rng is None:
        raise CompileError("A random seed strategy needs a random source to pick the seed.")
    return rng.randrange(0, 2**32)


def resolve_bindings(recipe: Recipe, bindings: Bindings) -> dict[str, str | FileRef]:
    """Check ``bindings`` against the recipe's slots and fill text defaults."""
    slots = {s.name: s for s in recipe.slots}
    unknown = sorted(set(bindings) - set(slots))
    if unknown:
        raise SlotBindingError(unknown[0], f"This recipe has no input called {unknown[0]!r}.")
    out: dict[str, str | FileRef] = {}
    for slot in recipe.slots:
        label = slot.label or slot.name
        value = bindings.get(slot.name)
        if value is None or (isinstance(value, str) and not value.strip()):
            if slot.default is not None:
                out[slot.name] = slot.default
            elif slot.required:
                raise SlotBindingError(slot.name, f"Fill in “{label}” ({slot.name}) to run this.")
            continue
        if slot.kind == "text":
            if not isinstance(value, str):
                raise SlotBindingError(slot.name, f"“{label}” ({slot.name}) needs text.")
        elif not isinstance(value, FileRef):
            raise SlotBindingError(slot.name, f"“{label}” ({slot.name}) needs a file.")
        out[slot.name] = value
    return out


# ---------------------------------------------------------------------------------------------
# Driver


def graph_from(g: GraphBuilder, ctx: CompileContext, image: Ref) -> EngineGraph:
    """Wrap a finished graph builder around its IMAGE output (adds the ``SaveImage`` node)."""
    out = g.node("SaveImage", images=image, filename_prefix=f"p11/step-{ctx.step_index:02d}")
    return EngineGraph(
        ctx.step_index,
        ctx.recipe.steps[ctx.step_index].type,
        g.nodes,
        out[0],
        tuple(g.inputs),
        tuple(g.models),
        ctx.seed,
        g.size,
        g.prep,
        g.likeness,
    )


def compile(
    recipe: Recipe,
    bindings: Bindings,
    registry: ModelRegistry,
    *,
    seed: int | None = None,
    run_index: int = 0,
    image_sizes: ImageSizes | None = None,
) -> list[PlanItem]:
    """Compile ``recipe`` into plan items (engine graphs and local steps), in order.

    A step compiles to one item, or (``replace_background``) to a local step plus its engine tail;
    each item's output is the input of the next, and the last item of a step is the step's output.
    ``seed`` overrides the recipe's strategy (the job runner resolves random seeds with
    ``resolve_seed`` and passes them here so the run is reproducible). ``image_sizes`` gives the
    pixel size of input files; a photo-edit ``generate`` sizes its graph by its photo.
    """
    if seed is None:
        seed = resolve_seed(recipe.seed, run_index)
    if not 0 <= seed <= MAX_SEED:
        raise CompileError(f"Seed {seed} is out of range (0 to {MAX_SEED}).")
    resolved = resolve_bindings(recipe, bindings)
    graphs: list[PlanItem] = []
    previous: int | None = None
    last_generate: Generate | None = None
    steps = recipe.steps
    for i, step in enumerate(steps):
        if step.is_modifier:
            continue
        if step.skippable_if_unbound and _has_unbound_optional(step, resolved, recipe):
            continue
        modifiers: list[Step] = []
        for later in steps[i + 1 :]:
            if not later.is_modifier:
                break
            modifiers.append(later)
        ctx = CompileContext(
            recipe,
            resolved,
            registry,
            seed,
            i,
            tuple(modifiers),
            previous,
            last_generate,
            image_sizes or {},
        )
        plan_fn = _PLAN_COMPILERS.get(step.type)
        before = len(graphs)
        if plan_fn is not None:
            graphs.extend(plan_fn(step, ctx))
        else:
            fn = _STEP_COMPILERS.get(step.type)
            if fn is None:
                raise UnsupportedStepError(_unsupported(step.type, ctx))
            g = GraphBuilder()
            graphs.append(graph_from(g, ctx, fn(step, ctx, g)))
        if len(graphs) > before:
            previous = i
        if isinstance(step, Generate):
            last_generate = step
    return graphs


def _has_unbound_optional(step: Step, resolved: Bindings, recipe: Recipe) -> bool:
    """True when a named image input is an optional slot the run left empty."""
    slots = {s.name: s for s in recipe.slots}
    return any(
        name not in resolved and not slots[name].required for _, name, _ in step.image_slots()
    )


def _unsupported(step_type: str, ctx: CompileContext) -> str:
    when = _NOT_YET.get(step_type)
    suffix = f" (added in {when})" if when else ""
    return f"{ctx.where}: this P11 build cannot run {step_type!r} steps yet{suffix}."


# ---------------------------------------------------------------------------------------------
# Built-in step compilers: generate and upscale


def _sampler(
    step: Generate | Inpaint, info: ModelInfo, ctx: CompileContext
) -> tuple[str, str, int, float, int]:
    d = info.defaults
    if d is None:
        raise CompileError(f"{ctx.where}: model {info.manifest_id!r} has no sampler defaults.")
    o = step.sampler
    name = (o.sampler_name if o and o.sampler_name else None) or d.sampler_name
    sched = (o.scheduler if o and o.scheduler else None) or d.scheduler
    steps = (o.steps if o and o.steps else None) or d.steps
    cfg = o.cfg if o and o.cfg is not None else d.cfg
    clip_skip = (o.clip_skip if o and o.clip_skip else None) or d.clip_skip
    if name not in SAMPLERS:
        raise CompileError(f"{ctx.where}: unknown sampler {name!r}.")
    if sched not in SCHEDULERS:
        raise CompileError(f"{ctx.where}: unknown scheduler {sched!r}.")
    return name, sched, steps, cfg, clip_skip


def _hires_steps(info: ModelInfo, steps: int) -> int:
    base = info.defaults.hires_steps if info.defaults and info.defaults.hires_steps else 0
    return base or max(1, steps // 2)


def _style(step_style: str | None, ctx: CompileContext) -> StylePreset | None:
    if step_style is None:
        return None
    style = STYLES.get(step_style)
    if style is None:
        raise CompileError(f"{ctx.where}: unknown style {step_style!r}.")
    return style


def _aspect(aspect_id: str, ctx: CompileContext) -> AspectPreset:
    aspect = ASPECTS.get(aspect_id)
    if aspect is None:
        raise CompileError(f"{ctx.where}: unknown aspect preset {aspect_id!r}.")
    return aspect


def _tiled(g: GraphBuilder, cls: str, **inputs: Any) -> Ref:
    return g.node(
        cls,
        **inputs,
        tile_size=VAE_TILE,
        overlap=VAE_OVERLAP,
        temporal_size=64,
        temporal_overlap=8,
    )


def compile_generate(step: Generate, ctx: CompileContext, g: GraphBuilder) -> Ref:
    style = _style(step.style, ctx)
    ckpt = ctx.model(step.model, style.model if style else DEFAULT_MODEL, "checkpoint")
    if ckpt.family is None:
        raise CompileError(f"{ctx.where}: model {ckpt.manifest_id!r} has no model family.")
    family = ckpt.family
    sampler, scheduler, steps, cfg, clip_skip = _sampler(step, ckpt, ctx)
    aspect = _aspect(step.aspect or (style.aspect if style else "16:9-1920x1080"), ctx)

    g.use_model(ckpt)
    loader = g.node("CheckpointLoaderSimple", ckpt_name=ckpt.filename)
    model: Ref = [loader[0], 0]
    clip: Ref = [loader[0], 1]
    vae: Ref = [loader[0], 2]
    vae_ref = step.vae or (ModelRef(manifest_id=ckpt.vae) if ckpt.vae else None)
    if vae_ref is not None:
        vae_info = ctx.model(vae_ref, vae_ref.manifest_id, "vae")
        g.use_model(vae_info)
        vae = g.node("VAELoader", vae_name=vae_info.filename)
    for lora in step.loras:
        info = ctx.model(lora.model, lora.model.manifest_id, "lora")
        g.use_model(info)
        lo = g.node(
            "LoraLoader",
            model=model,
            clip=clip,
            lora_name=info.filename,
            strength_model=lora.strength_model,
            strength_clip=lora.strength_clip,
        )
        model, clip = [lo[0], 0], [lo[0], 1]
    if clip_skip > 1:
        clip = g.node("CLIPSetLastLayer", clip=clip, stop_at_clip_layer=-clip_skip)

    prompt = ctx.text(step.prompt)
    negative = ctx.text(step.negative)
    positive_text = style.positive(prompt) if style else prompt.strip()
    negative_text = style.negative_for(negative) if style else negative.strip()
    positive = g.node("CLIPTextEncode", text=positive_text, clip=clip)
    negative_c = g.node("CLIPTextEncode", text=negative_text, clip=clip)

    cond = Conditioning(model, clip, vae, positive, negative_c, family)
    for mod in ctx.modifiers:
        hook = _MODIFIERS.get(mod.type)
        if hook is None:
            raise UnsupportedStepError(_unsupported(mod.type, ctx))
        cond = hook(mod, ctx, g, cond)

    width, height = aspect.size_for(family)
    out = aspect.output or (width, height)
    chain = step.chain or (aspect.quality_chain if step.quality else aspect.chain)
    denoise = 1.0
    if step.is_img2img:
        # Start from a photo (ADR-0038): its own aspect, the nearest native bucket, then the
        # usual chain toward its own size; the aspect preset applies only if the size is unknown.
        photo, ref = _photo_input(step, ctx)
        size = ctx.image_sizes.get(ref)
        if size is not None:
            width, height = nearest_bucket(family, *size)
            out = photo_output((width, height), *size)
            chain = step.chain or ("latent" if step.quality else "model")
        denoise = img2img_denoise(step)
        if not (step.sampler and step.sampler.steps):
            steps = max(steps, IMG2IMG_MIN_STEPS[img2img_preset(step)])
        load = g.node("LoadImage", image=photo.placeholder)
        g.inputs.append(replace(photo, node_id=load[0]))
        pixels = g.node(
            "ImageScale",
            image=load,
            upscale_method="lanczos",
            width=width,
            height=height,
            crop="center",
        )
        latent = g.node("VAEEncode", pixels=pixels, vae=cond.vae)
        if step.batch_size > 1:
            latent = g.node("RepeatLatentBatch", samples=latent, amount=step.batch_size)
    else:
        latent = g.node("EmptyLatentImage", width=width, height=height, batch_size=step.batch_size)
    if out == (width, height):
        chain = "native"
    base = g.node(
        "KSampler",
        "base",
        model=cond.model,
        seed=ctx.seed,
        steps=steps,
        cfg=cfg,
        sampler_name=sampler,
        scheduler=scheduler,
        positive=cond.positive,
        negative=cond.negative,
        latent_image=latent,
        denoise=denoise,
    )

    def hires(samples: Ref, denoise: float) -> Ref:
        return g.node(
            "KSampler",
            "hires",
            model=cond.model,
            seed=(ctx.seed + 1) % (MAX_SEED + 1),
            steps=_hires_steps(ckpt, steps),
            cfg=cfg,
            sampler_name=sampler,
            scheduler=scheduler,
            positive=cond.positive,
            negative=cond.negative,
            latent_image=samples,
            denoise=denoise,
        )

    if chain == "native":
        g.size = (width, height)
        return g.node("VAEDecode", samples=base, vae=cond.vae)
    g.size = out
    if chain == "latent":
        up = g.node(
            "LatentUpscale",
            samples=base,
            upscale_method="bislerp",
            width=out[0],
            height=out[1],
            crop="disabled",
        )
        return _tiled(g, "VAEDecodeTiled", samples=hires(up, HIRES_DENOISE["latent"]), vae=cond.vae)
    image = g.node("VAEDecode", samples=base, vae=cond.vae)
    image = _model_upscale(g, ctx, None, image)
    image = g.node(
        "ImageScale",
        image=image,
        upscale_method="lanczos",
        width=out[0],
        height=out[1],
        crop="disabled",
    )
    if chain == "both":
        enc = _tiled(g, "VAEEncodeTiled", pixels=image, vae=cond.vae)
        return _tiled(g, "VAEDecodeTiled", samples=hires(enc, HIRES_DENOISE["both"]), vae=cond.vae)
    return image


def img2img_preset(step: Generate) -> str:
    """The photo-edit preset a step runs as (its own, else the one nearest its ``denoise``)."""
    if step.denoise_preset is not None:
        return step.denoise_preset
    if step.denoise is None:
        return IMG2IMG_DEFAULT_PRESET
    return min(IMG2IMG_PRESETS, key=lambda k: abs(IMG2IMG_PRESETS[k] - (step.denoise or 0.0)))


def img2img_denoise(step: Generate) -> float:
    """The strength a photo edit samples with: the preset's tuned value, else ``denoise``."""
    if step.denoise_preset is None and step.denoise is not None:
        return step.denoise
    return IMG2IMG_PRESETS[img2img_preset(step)]


def nearest_bucket(family: Family, width: int, height: int) -> tuple[int, int]:
    """The family's native bucket whose aspect ratio is nearest ``width:height`` (log scale)."""
    if width <= 0 or height <= 0:
        raise CompileError("The photo has no size.")
    want = math.log(width / height)
    return min(BUCKETS[family], key=lambda b: abs(math.log(b[0] / b[1]) - want))


def photo_output(bucket: tuple[int, int], width: int, height: int) -> tuple[int, int]:
    """Final size of a photo edit: the bucket scaled toward the photo's own pixel count, capped
    at the largest wallpaper preset; the bucket itself when that would be no real upscale."""
    bw, bh = bucket
    factor = math.sqrt(min(width * height, IMG2IMG_MAX_PIXELS) / (bw * bh))
    if factor < IMG2IMG_MIN_UPSCALE:
        return bucket
    return (int(bw * factor) // 8 * 8, int(bh * factor) // 8 * 8)


def _photo_input(step: Generate, ctx: CompileContext) -> tuple[GraphInput, str]:
    """The photo a photo edit starts from: its slot, else the recipe's source (never the
    previous step), and the file reference its size is looked up by."""
    if step.image_slot is not None:
        inp = ctx.resolve_input(step.image_slot)
    elif ctx.recipe.source_image is not None:
        inp = GraphInput("", "source", "p11:source", file=ctx.recipe.source_image)
    else:
        raise CompileError(f"{ctx.where}: add a photo to start from, or turn the photo edit off.")
    assert inp.file is not None
    return inp, inp.file.ref


def _model_upscale(g: GraphBuilder, ctx: CompileContext, ref: ModelRef | None, image: Ref) -> Ref:
    info = ctx.model(ref, DEFAULT_UPSCALER, "upscale")
    g.use_model(info)
    loader = g.node("UpscaleModelLoader", model_name=info.filename)
    return g.node("ImageUpscaleWithModel", upscale_model=loader, image=image)


def compile_upscale(step: Upscale, ctx: CompileContext, g: GraphBuilder) -> Ref:
    image = ctx.load_image(g, step.image_slot)
    target = (step.width, step.height) if step.width and step.height else None
    scale = step.scale or 2.0

    def resize(img: Ref) -> Ref:
        if target:
            return g.node(
                "ImageScale",
                image=img,
                upscale_method="lanczos",
                width=target[0],
                height=target[1],
                crop="disabled",
            )
        return g.node("ImageScaleBy", image=img, upscale_method="lanczos", scale_by=scale)

    def model_up(img: Ref) -> Ref:
        """Model upscaler, then resize to the target or to ``scale`` overall."""
        info = ctx.model(step.upscaler, DEFAULT_UPSCALER, "upscale")
        up = _model_upscale(g, ctx, step.upscaler, img)
        if target:
            return resize(up)
        factor = scale / (info.scale or 1)
        if abs(factor - 1.0) < 1e-9:
            return up
        return g.node("ImageScaleBy", image=up, upscale_method="lanczos", scale_by=round(factor, 4))

    if step.chain == "model":
        g.size = target
        return model_up(image)

    # latent / both: a refinement pass needs a checkpoint and a prompt.
    gen = ctx.last_generate
    style = _style(gen.style, ctx) if gen else None
    default_ckpt = (gen.model.manifest_id if gen and gen.model else None) or (
        style.model if style else DEFAULT_MODEL
    )
    ckpt = ctx.model(step.model, default_ckpt, "checkpoint")
    d = ckpt.defaults
    if d is None:
        raise CompileError(f"{ctx.where}: model {ckpt.manifest_id!r} has no sampler defaults.")
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

    if step.chain == "both":
        image = model_up(image)
        latent = _tiled(g, "VAEEncodeTiled", pixels=image, vae=vae)
    else:
        latent = _tiled(g, "VAEEncodeTiled", pixels=image, vae=vae)
        if target:
            latent = g.node(
                "LatentUpscale",
                samples=latent,
                upscale_method="bislerp",
                width=target[0],
                height=target[1],
                crop="disabled",
            )
        else:
            latent = g.node(
                "LatentUpscaleBy", samples=latent, upscale_method="bislerp", scale_by=scale
            )
    denoise = step.denoise if step.denoise is not None else HIRES_DENOISE[step.chain]
    refined = g.node(
        "KSampler",
        "hires",
        model=model,
        seed=ctx.seed,
        steps=_hires_steps(ckpt, d.steps),
        cfg=d.cfg,
        sampler_name=d.sampler_name,
        scheduler=d.scheduler,
        positive=positive,
        negative=negative_c,
        latent_image=latent,
        denoise=denoise,
    )
    g.size = target
    return _tiled(g, "VAEDecodeTiled", samples=refined, vae=vae)


register_step("generate", compile_generate)
register_step("upscale", compile_upscale)

# Step compilers of later phases register themselves on import (after the names above exist).
from . import steps as _steps  # noqa: E402, F401

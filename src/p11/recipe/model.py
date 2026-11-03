"""Recipe schema v1 (spec R6, ADR-0007): the versioned source of truth for templates and runs.

Everything here is a frozen Pydantic v2 model with ``extra="forbid"``, so a typo in a template is
an error instead of a silently ignored field. Collections are tuples so a frozen recipe is
immutable all the way down. Model references are manifest IDs (``ModelRef``), never file paths.

Text fields of steps may contain ``{{slot}}`` placeholders naming a ``text`` slot; image inputs name
an image-kind slot, or leave it empty to take the previous step's output (or ``source_image``).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Any, ClassVar, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1

#: Largest seed P11 stores: JavaScript's safe integer, so the frontend never rounds one.
MAX_SEED = 2**53 - 1

ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
SLOT_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")

Seed = Annotated[int, Field(ge=0, le=MAX_SEED)]
Unit = Annotated[float, Field(ge=0.0, le=1.0)]

#: Largest inline (fixed) inpaint mask, base64 characters (~300 KB of PNG).
MAX_INLINE_MASK = 400_000


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelRef(_Frozen):
    """A model by manifest ID (Phase 06), optionally pinned to a hash the compiler checks."""

    manifest_id: str = Field(pattern=ID_PATTERN)
    sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)


class FileRef(_Frozen):
    """A file P11 stored itself (an upload or an earlier output), by opaque ID, not contents."""

    ref: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
    sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _no_traversal(self) -> FileRef:
        if any(part in ("", ".", "..") for part in self.ref.split("/")):
            raise ValueError("file reference must not contain empty, '.' or '..' segments")
        return self


# ---------------------------------------------------------------------------------------------
# Seed strategies


class FixedSeed(_Frozen):
    kind: Literal["fixed"] = "fixed"
    value: Seed


class RandomSeed(_Frozen):
    kind: Literal["random"] = "random"


class IncrementSeed(_Frozen):
    """Run ``i`` (0-based) of a batch or re-run uses ``start + i``."""

    kind: Literal["increment"] = "increment"
    start: Seed


SeedStrategy = Annotated[FixedSeed | RandomSeed | IncrementSeed, Field(discriminator="kind")]


# ---------------------------------------------------------------------------------------------
# Slots

SlotKind = Literal["text", "image", "face_image", "background_image", "mask", "video"]
IMAGE_KINDS: frozenset[str] = frozenset({"image", "face_image", "background_image", "mask"})


class Slot(_Frozen):
    """A named input the user fills when applying a template (e.g. "face photo", "logo text")."""

    name: str = Field(pattern=SLOT_PATTERN)
    kind: SlotKind
    label: str | None = Field(default=None, max_length=80)
    required: bool = True
    default: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _default_only_for_text(self) -> Slot:
        if self.default is not None and self.kind != "text":
            raise ValueError(f"slot {self.name!r}: only text slots can have a default")
        return self


# ---------------------------------------------------------------------------------------------
# Steps

Chain = Literal["native", "model", "latent", "both"]


class SamplerOverride(_Frozen):
    """Advanced-mode overrides (R18); ``None`` keeps the model's default from the manifest."""

    sampler_name: str | None = Field(default=None, max_length=64)
    scheduler: str | None = Field(default=None, max_length=64)
    steps: int | None = Field(default=None, ge=1, le=200)
    cfg: float | None = Field(default=None, ge=0.0, le=30.0)
    clip_skip: int | None = Field(default=None, ge=1, le=12)


class LoraRef(_Frozen):
    model: ModelRef
    strength_model: float = Field(default=1.0, ge=-5.0, le=5.0)
    strength_clip: float = Field(default=1.0, ge=-5.0, le=5.0)


class _Step(_Frozen):
    #: Image-slot fields of this step and the slot kinds each one accepts.
    image_fields: ClassVar[tuple[tuple[str, frozenset[str]], ...]] = ()
    #: Free-text fields that may contain ``{{slot}}`` placeholders.
    text_fields: ClassVar[tuple[str, ...]] = ()

    def image_slots(self) -> Iterator[tuple[str, str, frozenset[str]]]:
        for field, kinds in self.image_fields:
            value = getattr(self, field)
            if value is not None:
                yield field, value, kinds

    def text_values(self) -> Iterator[tuple[str, str]]:
        for field in self.text_fields:
            yield field, getattr(self, field)

    @property
    def is_modifier(self) -> bool:
        """Modifiers condition the ``generate`` step they follow instead of producing a graph."""
        return False


class Generate(_Step):
    """Text-to-image at an aspect preset's native bucket, plus the preset's upscale chain (R3)."""

    type: Literal["generate"] = "generate"
    prompt: str = Field(max_length=4000)
    negative: str = Field(default="", max_length=4000)
    style: str | None = Field(default="photoreal", max_length=64)
    #: Aspect preset ID; ``None`` uses the style's default aspect.
    aspect: str | None = Field(default=None, max_length=64)
    model: ModelRef | None = None
    vae: ModelRef | None = None
    loras: tuple[LoraRef, ...] = Field(default=(), max_length=8)
    sampler: SamplerOverride | None = None
    chain: Chain | None = None
    quality: bool = False
    batch_size: int = Field(default=1, ge=1, le=4)

    text_fields = ("prompt", "negative")


class Upscale(_Step):
    """Upscale an existing image (follow-up action or a template step) with an R3 chain."""

    type: Literal["upscale"] = "upscale"
    image_slot: str | None = None
    chain: Literal["model", "latent", "both"] = "model"
    scale: float | None = Field(default=2.0, gt=1.0, le=4.0)
    width: int | None = Field(default=None, ge=64, le=8192)
    height: int | None = Field(default=None, ge=64, le=8192)
    upscaler: ModelRef | None = None
    model: ModelRef | None = None
    denoise: Unit | None = None
    prompt: str = Field(default="", max_length=4000)
    negative: str = Field(default="", max_length=4000)

    image_fields = (("image_slot", IMAGE_KINDS - {"mask"}),)
    text_fields = ("prompt", "negative")

    @model_validator(mode="after")
    def _size(self) -> Upscale:
        if (self.width is None) != (self.height is None):
            raise ValueError("upscale: give both width and height, or neither")
        if self.width is None and self.scale is None:
            raise ValueError("upscale: give a scale or a target width and height")
        return self


class Inpaint(_Step):
    """Repaint the masked part of an image (Phase 10, ``recipe/steps/inpaint.py``, ADR-0025).

    The mask comes from ``mask_slot`` (painted or uploaded per run) or, in a template saved with a
    fixed mask, from ``mask_png`` (a small greyscale PNG, base64; a shape, never a photo). White is
    repainted. ``denoise_preset`` (UI: Subtle fix / Change / Replace) overrides ``denoise`` with the
    tuned strength from ``presets.INPAINT_PRESETS``; ``None`` uses ``denoise`` as given.
    ``crop`` ("only masked area at full resolution") inpaints a padded box around the mask at the
    model's working size and pastes it back, so small fixes keep their detail.
    """

    type: Literal["inpaint"] = "inpaint"
    image_slot: str | None = None
    mask_slot: str | None = None
    mask_png: str | None = Field(
        default=None, min_length=8, max_length=MAX_INLINE_MASK, pattern=r"^[A-Za-z0-9+/]+=*$"
    )
    prompt: str = Field(default="", max_length=4000)
    negative: str = Field(default="", max_length=4000)
    denoise: Unit = 0.6
    denoise_preset: Literal["subtle", "balanced", "major"] | None = None
    grow_mask_px: int = Field(default=8, ge=0, le=256)
    mask_blur_px: int = Field(default=12, ge=0, le=128)
    crop: bool = True
    padding_px: int = Field(default=48, ge=0, le=1024)
    model: ModelRef | None = None
    sampler: SamplerOverride | None = None

    image_fields = (("image_slot", IMAGE_KINDS - {"mask"}), ("mask_slot", frozenset({"mask"})))
    text_fields = ("prompt", "negative")

    @model_validator(mode="after")
    def _one_mask(self) -> Inpaint:
        if (self.mask_slot is None) == (self.mask_png is None):
            raise ValueError("inpaint: give exactly one of mask_slot or mask_png")
        return self


class ReplaceBackground(_Step):
    """Cut out the subject and put it on a photo background (Phase 11 compiles it)."""

    type: Literal["replace_background"] = "replace_background"
    image_slot: str | None = None
    background_slot: str
    mask_mode: Literal["auto", "manual"] = "auto"
    mask_slot: str | None = None
    segmentation_model: ModelRef | None = None
    colour_match: bool = True
    feather_px: int = Field(default=8, ge=0, le=128)
    relight: bool = False
    relight_denoise: Unit = 0.25

    image_fields = (
        ("image_slot", IMAGE_KINDS - {"mask"}),
        ("background_slot", frozenset({"background_image", "image"})),
        ("mask_slot", frozenset({"mask"})),
    )

    @model_validator(mode="after")
    def _manual_needs_mask(self) -> ReplaceBackground:
        if self.mask_mode == "manual" and self.mask_slot is None:
            raise ValueError("replace_background: manual mask mode needs mask_slot")
        return self


class FaceSwap(_Step):
    """Put the face from ``face_slot`` onto the target image (Phase 12 compiles it).

    The NSFW target guard (S5, ADR-0005) is not a field: it is always on and cannot be configured.
    """

    type: Literal["face_swap"] = "face_swap"
    face_slot: str
    image_slot: str | None = None
    source_face_index: int = Field(default=0, ge=0, le=16)
    target_face_index: int = Field(default=0, ge=0, le=16)
    swapper_model: ModelRef | None = None
    restore: bool = True
    restore_model: ModelRef | None = None
    restore_visibility: Unit = 1.0

    image_fields = (
        ("face_slot", frozenset({"face_image", "image"})),
        ("image_slot", IMAGE_KINDS - {"mask"}),
    )


class Pose(_Step):
    """Condition the preceding ``generate`` step on a pose (Phase 12 compiles it)."""

    type: Literal["pose"] = "pose"
    pose_slot: str
    preprocess: bool = True
    controlnet: ModelRef | None = None
    strength: Unit = 0.8
    start: Unit = 0.0
    end: Unit = 1.0

    image_fields = (("pose_slot", frozenset({"image"})),)

    @property
    def is_modifier(self) -> bool:
        return True


class Reference(_Step):
    """Condition the preceding ``generate`` step on a style/character image (Phase 12)."""

    type: Literal["reference"] = "reference"
    image_slot: str
    mode: Literal["style", "character", "face"] = "style"
    ipadapter: ModelRef | None = None
    weight: Unit = 0.7
    start: Unit = 0.0
    end: Unit = 1.0

    image_fields = (("image_slot", frozenset({"image", "face_image"})),)

    @property
    def is_modifier(self) -> bool:
        return True


class TextOverlay(_Step):
    """Exact text drawn with a bundled font (R23; Phase 14 implements it, outside the engine)."""

    type: Literal["text_overlay"] = "text_overlay"
    text: str = Field(min_length=1, max_length=200)
    font: str = Field(default="sans", max_length=64)
    size_pct: float = Field(default=12.0, gt=0.0, le=100.0)
    colour: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
    position: Literal[
        "top-left",
        "top",
        "top-right",
        "left",
        "center",
        "right",
        "bottom-left",
        "bottom",
        "bottom-right",
    ] = "bottom"
    margin_pct: float = Field(default=5.0, ge=0.0, le=50.0)
    stroke_px: int = Field(default=0, ge=0, le=64)
    stroke_colour: str = Field(default="#000000", pattern=r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
    shadow: bool = False
    also_prompt_model: bool = False

    text_fields = ("text",)


Step = Annotated[
    Generate | Upscale | Inpaint | ReplaceBackground | FaceSwap | Pose | Reference | TextOverlay,
    Field(discriminator="type"),
]
StepType = Literal[
    "generate",
    "upscale",
    "inpaint",
    "replace_background",
    "face_swap",
    "pose",
    "reference",
    "text_overlay",
]
STEP_TYPES: tuple[str, ...] = (
    "generate",
    "upscale",
    "inpaint",
    "replace_background",
    "face_swap",
    "pose",
    "reference",
    "text_overlay",
)


# ---------------------------------------------------------------------------------------------
# Recipe


class Recipe(_Frozen):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    tags: tuple[Annotated[str, Field(min_length=1, max_length=40)], ...] = Field(
        default=(), max_length=20
    )
    folder: str = Field(default="", max_length=120)
    steps: tuple[Step, ...] = Field(min_length=1, max_length=32)
    slots: tuple[Slot, ...] = Field(default=(), max_length=16)
    seed: SeedStrategy = Field(default_factory=RandomSeed)
    created_at: AwareDatetime
    source_image: FileRef | None = None

    @model_validator(mode="after")
    def _references(self) -> Recipe:
        slots = {s.name: s for s in self.slots}
        if len(slots) != len(self.slots):
            raise ValueError("slot names must be unique")
        for i, step in enumerate(self.steps):
            where = f"step {i + 1} ({step.type})"
            for field, name, kinds in step.image_slots():
                slot = slots.get(name)
                if slot is None:
                    raise ValueError(f"{where}: {field} names unknown slot {name!r}")
                if slot.kind not in kinds:
                    raise ValueError(
                        f"{where}: {field} needs a slot of kind {sorted(kinds)}, "
                        f"but {name!r} is {slot.kind!r}"
                    )
            for field, text in step.text_values():
                for name in PLACEHOLDER.findall(text):
                    slot = slots.get(name)
                    if slot is None or slot.kind != "text":
                        raise ValueError(
                            f"{where}: {field} uses {{{{{name}}}}}, which is not a text slot"
                        )
            if step.is_modifier:
                prev = next((s for s in reversed(self.steps[:i]) if not s.is_modifier), None)
                if not isinstance(prev, Generate):
                    raise ValueError(f"{where}: must follow a generate step")
        return self

    @classmethod
    def new(cls, name: str, steps: list[Any] | tuple[Any, ...], **fields: Any) -> Recipe:
        """Build a recipe with a fresh ID and ``created_at`` (not pure: uuid4 and the clock)."""
        fields.setdefault("id", uuid.uuid4().hex)
        fields.setdefault("created_at", datetime.now(UTC))
        return cls(name=name, steps=tuple(steps), **fields)

    def to_json(self) -> str:
        """Canonical JSON (stable key order) used for templates, sidecars and PNG chunks."""
        return self.model_dump_json(indent=2, exclude_none=False)

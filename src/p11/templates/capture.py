"""Save as Template: turn what produced an image into a reusable recipe (spec §4, Phase 09).

Pure: takes a ``RunRecord`` and the user's choices, returns a ``Recipe``. Slot inference follows
three rules, none of which looks at step types, so inpaint, background and face steps need no
changes here:

* slots the run already had stay slots; a text slot that was filled for the run keeps that text as
  its default (so the template reproduces the run until the user types something else);
* an image the run started from (``source_image``, a follow-up on an earlier output) becomes a
  ``source`` image slot on the first step that takes one, so a template never points at a gallery
  image that may be deleted;
* the prompt becomes a ``prompt`` text slot only when the user marks it variable;
* an inpaint mask stays a slot (paint or upload one per run) unless the user keeps it **fixed**:
  then the mask (a shape, never a photo; made small by ``media.inpaint.compact_mask``) is stored in
  the step as ``mask_png`` and the slot goes (ADR-0025).

Uploads and other bound photos are never copied into a template (S6).
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Literal

from ..outputs.metadata import RunRecord
from ..recipe.model import (
    PLACEHOLDER,
    FixedSeed,
    Generate,
    Inpaint,
    RandomSeed,
    Recipe,
    ReplaceBackground,
    Slot,
)

SeedMode = Literal["fixed", "random"]
MaskMode = Literal["auto", "slot", "fixed"]
MAX_SLOTS = 16


def _free_name(taken: set[str], wanted: str) -> str:
    name, n = wanted, 2
    while name in taken:
        name = f"{wanted}_{n}"
        n += 1
    return name


def capture_template(
    record: RunRecord,
    *,
    name: str,
    folder: str = "",
    tags: Sequence[str] = (),
    seed: SeedMode = "fixed",
    variable_prompt: bool = False,
    masks: Mapping[str, bytes] | None = None,
    mask_mode: MaskMode = "slot",
) -> Recipe:
    """The template for ``record``: a new recipe ID, the chosen seed strategy and inferred slots.

    ``masks`` maps a mask slot to the (compacted) mask PNG to keep fixed in the template;
    ``mask_mode`` "auto" makes ``replace_background`` steps segment each run's subject instead.
    """
    recipe = record.recipe
    slots: list[Slot] = []
    for slot in recipe.slots:
        bound = record.bindings.get(slot.name)
        if slot.kind == "text" and isinstance(bound, str) and bound.strip():
            slot = slot.model_copy(update={"default": bound})
        slots.append(slot)
    steps = list(recipe.steps)
    taken = {s.name for s in slots}

    if recipe.source_image is not None:
        for i, step in enumerate(steps):
            field = next(
                (f for f, kinds in step.image_fields
                 if "image" in kinds and getattr(step, f) is None),
                None,
            )  # fmt: skip
            if field is None:
                continue
            slot_name = _free_name(taken, "source")
            taken.add(slot_name)
            slots.append(Slot(name=slot_name, kind="image", label="Source image"))
            steps[i] = step.model_copy(update={field: slot_name})
            break

    if variable_prompt:
        for i, step in enumerate(steps):
            if isinstance(step, Generate) and not PLACEHOLDER.search(step.prompt):
                slot_name = _free_name(taken, "prompt")
                taken.add(slot_name)
                slots.append(
                    Slot(
                        name=slot_name,
                        kind="text",
                        label="Prompt",
                        required=False,
                        default=step.prompt or None,
                    )
                )
                steps[i] = step.model_copy(update={"prompt": "{{" + slot_name + "}}"})
                break

    fixed = set()
    for i, step in enumerate(steps):
        if not isinstance(step, (Inpaint, ReplaceBackground)) or step.mask_slot is None:
            continue
        if mask_mode == "auto" and isinstance(step, ReplaceBackground):
            # Segment the subject of each run (the template re-runs on new subjects).
            steps[i] = step.model_copy(
                update={"mask_mode": "auto", "mask_slot": None, "mask_png": None}
            )
            fixed.add(step.mask_slot)
        elif step.mask_slot in (masks or {}):
            png = base64.b64encode((masks or {})[step.mask_slot]).decode()
            steps[i] = step.model_copy(update={"mask_slot": None, "mask_png": png})
            fixed.add(step.mask_slot)
    still_used = {name for step in steps for _, name, _ in step.image_slots()}
    slots = [s for s in slots if s.name not in fixed or s.name in still_used]

    return Recipe(
        id=uuid.uuid4().hex,
        name=name.strip()[:120] or recipe.name,
        tags=tuple(dict.fromkeys(t.strip()[:40] for t in tags if t.strip()))[:20],
        folder=folder,
        steps=tuple(steps),
        slots=tuple(slots[:MAX_SLOTS]),
        seed=FixedSeed(value=record.seed) if seed == "fixed" else RandomSeed(),
        created_at=datetime.now(UTC),
        source_image=None,
    )

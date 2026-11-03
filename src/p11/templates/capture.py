"""Save as Template: turn what produced an image into a reusable recipe (spec §4, Phase 09).

Pure: takes a ``RunRecord`` and the user's choices, returns a ``Recipe``. Slot inference follows
three rules, none of which looks at step types, so inpaint, background and face steps need no
changes here:

* slots the run already had stay slots; a text slot that was filled for the run keeps that text as
  its default (so the template reproduces the run until the user types something else);
* an image the run started from (``source_image``, a follow-up on an earlier output) becomes a
  ``source`` image slot on the first step that takes one, so a template never points at a gallery
  image that may be deleted;
* the prompt becomes a ``prompt`` text slot only when the user marks it variable.

Uploads and other bound files are never copied into a template (S6).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from ..outputs.metadata import RunRecord
from ..recipe.model import PLACEHOLDER, FixedSeed, Generate, RandomSeed, Recipe, Slot

SeedMode = Literal["fixed", "random"]
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
) -> Recipe:
    """The template for ``record``: a new recipe ID, the chosen seed strategy and inferred slots."""
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
            field = next((f for f, _ in step.image_fields if getattr(step, f) is None), None)
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

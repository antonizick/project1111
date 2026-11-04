"""Which steps carry a person's likeness into a picture (S5, ADR-0037). Pure.

A ``face_swap`` puts a face from a photo into a picture. A ``reference`` step does the same through
the generation when it uses IP-Adapter Plus Face (``character``/``face`` mode) or any adapter other
than the stock style adapter, which fails safe for user-added adapters. The job runner checks the
output of such a step, and of every later step and later job made from it, with the S5 guard.
"""

from __future__ import annotations

from .model import FaceSwap, Recipe, Reference, Step
from .presets import DEFAULT_IPADAPTER


def carries_likeness(step: Step) -> bool:
    if isinstance(step, FaceSwap):
        return True
    if isinstance(step, Reference):
        adapter = step.ipadapter.manifest_id if step.ipadapter else DEFAULT_IPADAPTER
        return step.mode != "style" or adapter != DEFAULT_IPADAPTER
    return False


def recipe_carries_likeness(recipe: Recipe) -> bool:
    return any(carries_likeness(s) for s in recipe.steps)

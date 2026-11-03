"""Shared builders for the recipe/outputs/templates tests (synthetic data only, S6)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from p11.recipe.model import FixedSeed, Generate, Recipe

FIXED_TIME = datetime(2026, 11, 2, 18, 30, 0, tzinfo=UTC)


def recipe(*steps: Any, **fields: Any) -> Recipe:
    fields.setdefault("id", "r-test")
    fields.setdefault("name", "Test recipe")
    fields.setdefault("created_at", FIXED_TIME)
    fields.setdefault("seed", FixedSeed(value=1111))
    if not steps:
        steps = (Generate(prompt="a lighthouse on a rocky coast"),)
    return Recipe(steps=tuple(steps), **fields)

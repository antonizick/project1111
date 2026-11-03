import random

import pytest
from tests.helpers import recipe

from p11.recipe.model import FixedSeed, Generate, IncrementSeed, RandomSeed, Slot, Upscale
from p11.recipe.presets import ASPECTS, STYLES
from p11.recipe.variations import mutate_prompt, prompt_mutation, seed_variations


def test_seed_variations_from_fixed_and_increment() -> None:
    vs = seed_variations(recipe(seed=FixedSeed(value=100)), 3)
    assert [v.seed for v in vs] == [FixedSeed(value=s) for s in (101, 102, 103)]
    vs = seed_variations(recipe(seed=IncrementSeed(start=5)), 2)
    assert [v.seed.value for v in vs] == [6, 7]  # type: ignore[union-attr]
    assert seed_variations(recipe(), 0) == []
    assert all(v.steps == recipe().steps for v in vs)


def test_seed_variations_random_is_deterministic_and_distinct() -> None:
    r = recipe(seed=RandomSeed())
    a = seed_variations(r, 5, random.Random(3))
    b = seed_variations(r, 5, random.Random(3))
    assert a == b
    assert len({v.seed.value for v in a}) == 5  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="random source"):
        seed_variations(r, 2)


def test_mutate_prompt_is_deterministic_and_small() -> None:
    p = "photo of a misty lake, golden hour, pine forest, cinematic"
    a = mutate_prompt(p, random.Random(7))
    assert a == mutate_prompt(p, random.Random(7))
    assert a != p
    assert abs(len(a.split(",")) - len(p.split(","))) <= 1


def test_mutation_kinds_all_reachable() -> None:
    p = "photo of a misty lake, golden hour, pine forest"
    seen = {mutate_prompt(p, random.Random(i)) for i in range(60)}
    assert any("photograph of" in s or "shot of" in s for s in seen)  # synonym
    assert any(
        s.startswith("photo of a misty lake, pine forest, golden hour") for s in seen
    )  # swap
    assert any(len(s.split(", ")) == 4 for s in seen)  # adjective


def test_mutation_keeps_placeholders_and_first_phrase() -> None:
    p = "logo for {{brand}}, flat, minimalist"
    for i in range(30):
        out = mutate_prompt(p, random.Random(i))
        assert "{{brand}}" in out
        assert out.split(", ")[0] in ("logo for {{brand}}",)


def test_mutate_empty_prompt() -> None:
    assert mutate_prompt("  ", random.Random(0)) == "  "


def test_prompt_mutation_changes_only_generate_steps() -> None:
    r = recipe(
        Generate(prompt="a red car, cinematic"),
        Upscale(prompt="keep me"),
        slots=(Slot(name="t", kind="text"),),
    )
    out = prompt_mutation(r, random.Random(1))
    assert out.steps[1] == r.steps[1]
    assert out.steps[0].prompt != r.steps[0].prompt  # type: ignore[union-attr]
    assert prompt_mutation(r, random.Random(1)) == out


def test_preset_table_is_consistent() -> None:
    for style in STYLES.values():
        assert style.aspect in ASPECTS
        assert style.positive("x").count("x") >= 1
    for aspect in ASPECTS.values():
        for w, h in aspect.bucket.values():
            assert w % 8 == 0 and h % 8 == 0
        if aspect.output:
            assert aspect.output[0] % 8 == 0 and aspect.output[1] % 8 == 0
    assert ASPECTS["avatar-4:5"].size_for("sdxl") == (896, 1152)
    assert ASPECTS["16:9-1920x1080"].chain == "model"
    assert ASPECTS["16:9-2560x1440"].quality_chain == "latent"
    assert STYLES["3d-animated-avatar"].label == "3D animated avatar (bobblehead)"  # R17

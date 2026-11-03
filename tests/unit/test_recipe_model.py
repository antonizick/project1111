import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError
from tests.helpers import FIXED_TIME, recipe

from p11.recipe.migrate import loads
from p11.recipe.model import (
    MAX_SEED,
    FaceSwap,
    FileRef,
    FixedSeed,
    Generate,
    IncrementSeed,
    Inpaint,
    ModelRef,
    Pose,
    RandomSeed,
    Recipe,
    Reference,
    ReplaceBackground,
    Slot,
    TextOverlay,
    Upscale,
)


def test_minimal_recipe_round_trips() -> None:
    r = recipe()
    assert r.schema_version == 1
    assert Recipe.model_validate_json(r.to_json()) == r


def test_recipe_is_frozen() -> None:
    r = recipe()
    with pytest.raises(ValidationError):
        r.name = "other"  # type: ignore[misc]


def test_extra_fields_are_rejected() -> None:
    data = json.loads(recipe().to_json())
    data["steps"][0]["promt"] = "typo"
    with pytest.raises(ValidationError, match="promt"):
        Recipe.model_validate(data)


def test_discriminated_union_picks_step_class() -> None:
    r = recipe(
        Generate(prompt="x"),
        Pose(pose_slot="pose"),
        Reference(image_slot="ref"),
        Upscale(),
        TextOverlay(text="{{title}}"),
        slots=(
            Slot(name="pose", kind="image"),
            Slot(name="ref", kind="image"),
            Slot(name="title", kind="text"),
        ),
    )
    data = json.loads(r.to_json())
    back = Recipe.model_validate(data)
    assert [type(s) for s in back.steps] == [Generate, Pose, Reference, Upscale, TextOverlay]


def test_unknown_step_type_is_rejected() -> None:
    data = json.loads(recipe().to_json())
    data["steps"][0]["type"] = "teleport"
    with pytest.raises(ValidationError):
        Recipe.model_validate(data)


def test_all_step_types_serialise() -> None:
    slots = (
        Slot(name="mask", kind="mask"),
        Slot(name="bg", kind="background_image"),
        Slot(name="face", kind="face_image"),
    )
    r = recipe(
        Generate(prompt="x"),
        Inpaint(mask_slot="mask", denoise=0.3, denoise_preset="subtle"),
        ReplaceBackground(background_slot="bg"),
        FaceSwap(face_slot="face"),
        slots=slots,
    )
    assert [s.type for s in loads(r.to_json()).steps] == [
        "generate", "inpaint", "replace_background", "face_swap",
    ]  # fmt: skip


def test_face_swap_has_no_guard_switch() -> None:
    # S5 / ADR-0005: the NSFW target guard is not configurable, so the schema has no field for it.
    fields = set(FaceSwap.model_fields)
    assert not {f for f in fields if "nsfw" in f or "guard" in f or "safe" in f}


@pytest.mark.parametrize(
    ("seed", "kind"),
    [
        (FixedSeed(value=5), "fixed"),
        (RandomSeed(), "random"),
        (IncrementSeed(start=9), "increment"),
    ],
)
def test_seed_strategies_round_trip(seed: object, kind: str) -> None:
    r = recipe(seed=seed)
    back = loads(r.to_json())
    assert back.seed.kind == kind
    assert back.seed == seed


def test_seed_range() -> None:
    FixedSeed(value=MAX_SEED)
    with pytest.raises(ValidationError):
        FixedSeed(value=MAX_SEED + 1)
    with pytest.raises(ValidationError):
        FixedSeed(value=-1)


def test_unknown_image_slot_is_named() -> None:
    with pytest.raises(ValidationError, match="unknown slot 'face'"):
        recipe(Generate(prompt="x"), FaceSwap(face_slot="face"))


def test_slot_kind_must_fit() -> None:
    with pytest.raises(ValidationError, match="'face' is 'text'"):
        recipe(
            Generate(prompt="x"),
            FaceSwap(face_slot="face"),
            slots=(Slot(name="face", kind="text"),),
        )


def test_placeholder_must_be_text_slot() -> None:
    with pytest.raises(ValidationError, match="not a text slot"):
        recipe(Generate(prompt="logo for {{brand}}"))
    with pytest.raises(ValidationError, match="not a text slot"):
        recipe(Generate(prompt="{{img}}"), slots=(Slot(name="img", kind="image"),))
    recipe(Generate(prompt="logo for {{ brand }}"), slots=(Slot(name="brand", kind="text"),))


def test_duplicate_slots_rejected() -> None:
    with pytest.raises(ValidationError, match="unique"):
        recipe(slots=(Slot(name="a", kind="text"), Slot(name="a", kind="image")))


def test_default_only_on_text_slots() -> None:
    with pytest.raises(ValidationError, match="only text slots"):
        Slot(name="a", kind="image", default="x")


def test_modifier_must_follow_generate() -> None:
    slots = (Slot(name="pose", kind="image"),)
    with pytest.raises(ValidationError, match="must follow a generate step"):
        recipe(Pose(pose_slot="pose"), slots=slots)
    with pytest.raises(ValidationError, match="must follow a generate step"):
        recipe(Generate(prompt="x"), Upscale(), Pose(pose_slot="pose"), slots=slots)
    recipe(Generate(prompt="x"), Pose(pose_slot="pose"), Reference(image_slot="pose"), slots=slots)


def test_upscale_size_rules() -> None:
    with pytest.raises(ValidationError, match="both width and height"):
        Upscale(width=100)
    with pytest.raises(ValidationError, match="scale or a target"):
        Upscale(scale=None)
    assert Upscale(scale=None, width=200, height=100).width == 200


def test_manual_background_needs_mask() -> None:
    with pytest.raises(ValidationError, match="mask_slot"):
        ReplaceBackground(background_slot="bg", mask_mode="manual")


@pytest.mark.parametrize("ref", ["../etc/passwd", "a//b", "a/./b", "/abs", ".hidden"])
def test_file_ref_rejects_traversal(ref: str) -> None:
    with pytest.raises(ValidationError):
        FileRef(ref=ref)


def test_model_ref_validation() -> None:
    ModelRef(manifest_id="realvisxl5-lightning", sha256="a" * 64)
    with pytest.raises(ValidationError):
        ModelRef(manifest_id="Bad ID")
    with pytest.raises(ValidationError):
        ModelRef(manifest_id="ok", sha256="xyz")


def test_new_assigns_id_and_time() -> None:
    a = Recipe.new("A", [Generate(prompt="x")])
    b = Recipe.new("A", [Generate(prompt="x")])
    assert a.id != b.id
    assert a.created_at.tzinfo is not None


def test_created_at_must_be_aware() -> None:
    with pytest.raises(ValidationError):
        recipe(created_at=FIXED_TIME.replace(tzinfo=None))


_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="{}"), max_size=200
)


@settings(max_examples=150, deadline=None)
@given(
    prompt=_text,
    negative=_text,
    name=st.text(min_size=1, max_size=120).filter(lambda s: s.strip() != "" or True),
    tags=st.lists(st.text(min_size=1, max_size=40), max_size=5),
    seed=st.integers(min_value=0, max_value=MAX_SEED),
    batch=st.integers(min_value=1, max_value=4),
    quality=st.booleans(),
    chain=st.sampled_from([None, "native", "model", "latent", "both"]),
)
def test_recipe_json_round_trip_property(
    prompt: str,
    negative: str,
    name: str,
    tags: list[str],
    seed: int,
    batch: int,
    quality: bool,
    chain: str | None,
) -> None:
    r = recipe(
        Generate(prompt=prompt, negative=negative, batch_size=batch, quality=quality, chain=chain),  # type: ignore[arg-type]
        name=name,
        tags=tuple(tags),
        seed=FixedSeed(value=seed),
    )
    assert loads(r.to_json()) == r
    assert loads(r.to_json().encode()) == r

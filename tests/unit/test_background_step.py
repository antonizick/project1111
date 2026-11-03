"""Phase 11 ``replace_background``: the schema, the compiler's plan items and the harmonize tail."""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError
from tests.helpers import recipe

from p11.recipe.compile import CompileError, LocalStep, SlotBindingError, compile
from p11.recipe.model import FileRef, Generate, ReplaceBackground, Slot
from p11.recipe.registry import PROVISIONAL_DEFAULT_SET

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "compile"
REG = PROVISIONAL_DEFAULT_SET
BG_SLOT = (Slot(name="bg", kind="background_image"),)
MASK_SLOT = (Slot(name="mask", kind="mask"),)


def mask_png(size: tuple[int, int], box: tuple[int, int, int, int]) -> bytes:
    img = Image.new("L", size, 0)
    ImageDraw.Draw(img).rectangle(box, fill=255)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def nodes_of(graph: Any, cls: str) -> list[dict[str, Any]]:
    return [n["inputs"] for n in graph.nodes.values() if n["class_type"] == cls]


# -- schema ------------------------------------------------------------------------------------


def test_schema_needs_exactly_one_background() -> None:
    ReplaceBackground(background_slot="bg")
    ReplaceBackground(background_colour="#102030")
    with pytest.raises(ValidationError, match="exactly one"):
        ReplaceBackground()
    with pytest.raises(ValidationError, match="exactly one"):
        ReplaceBackground(background_slot="bg", background_colour="#102030")


def test_schema_masks_follow_the_mode() -> None:
    ReplaceBackground(background_colour="#ffffff")  # auto: no mask
    ReplaceBackground(background_colour="#ffffff", mask_mode="manual", mask_slot="mask")
    ReplaceBackground(background_colour="#ffffff", mask_mode="manual", mask_png="aGVsbG8=")
    with pytest.raises(ValidationError, match="exactly one"):
        ReplaceBackground(background_colour="#ffffff", mask_mode="manual")
    with pytest.raises(ValidationError, match="auto mask mode"):
        ReplaceBackground(background_colour="#ffffff", mask_slot="mask")


def test_phase04_documents_still_load() -> None:
    step = ReplaceBackground.model_validate(
        {
            "type": "replace_background",
            "background_slot": "bg",
            "mask_mode": "manual",
            "mask_slot": "m",
            "colour_match": True,
            "feather_px": 8,
            "relight": True,
            "relight_denoise": 0.25,
        }
    )
    assert step.fit == "cover" and step.subject_scale == 1.0 and step.shadow is False
    assert step.colour_match_strength == 1.0 and step.mask_png is None


# -- compiler ----------------------------------------------------------------------------------


def test_auto_without_relight_is_a_local_step_only() -> None:
    r = recipe(
        ReplaceBackground(background_slot="bg"),
        slots=BG_SLOT,
        source_image=FileRef(ref="gallery/7"),
        id="bg-auto",
    )
    (item,) = compile(r, {"bg": FileRef(ref="img-bg")}, REG)
    assert isinstance(item, LocalStep)
    assert item.op == "replace_background" and item.step_type == "replace_background"
    assert item.models == ("birefnet-lite",)
    assert item.params["segmentation_model"] == "birefnet-lite"
    assert [i.placeholder for i in item.inputs] == ["image", "background"]
    assert [i.source for i in item.inputs] == ["source", "slot"]


def test_manual_mask_is_an_input_and_needs_no_model() -> None:
    r = recipe(
        ReplaceBackground(background_colour="#224466", mask_mode="manual", mask_slot="mask"),
        slots=MASK_SLOT,
        source_image=FileRef(ref="gallery/7"),
        id="bg-manual",
    )
    (item,) = compile(r, {"mask": FileRef(ref="img-mask")}, REG)
    assert isinstance(item, LocalStep)
    assert item.models == () and item.params["segmentation_model"] is None
    assert [(i.placeholder, i.kind) for i in item.inputs] == [("image", "image"), ("mask", "mask")]
    assert item.params["background_colour"] == "#224466"
    assert [i.placeholder for i in item.inputs].count("background") == 0


def test_fixed_mask_is_an_inline_input() -> None:
    png = mask_png((16, 16), (2, 2, 9, 9))
    r = recipe(
        ReplaceBackground(
            background_slot="bg", mask_mode="manual", mask_png=base64.b64encode(png).decode()
        ),
        slots=BG_SLOT,
        source_image=FileRef(ref="gallery/7"),
        id="bg-fixed",
    )
    (item,) = compile(r, {"bg": FileRef(ref="img-bg")}, REG)
    assert isinstance(item, LocalStep)
    (inline,) = [i for i in item.inputs if i.source == "inline"]
    assert inline.kind == "mask" and inline.data == png


def test_relight_adds_the_harmonize_tail() -> None:
    r = recipe(
        Generate(prompt="a product on a table", aspect="1:1-1024"),
        ReplaceBackground(background_slot="bg", relight=True, relight_denoise=0.3),
        slots=BG_SLOT,
        id="bg-relight",
    )
    _, first, tail = compile(r, {"bg": FileRef(ref="img-bg")}, REG)
    assert isinstance(first, LocalStep)
    assert first.engine is None and tail.step_index == 1 and tail.step_type == "replace_background"
    assert tail.prep is not None and tail.prep.image == "p11:local:image"
    assert tail.prep.mask == "p11:local:mask"
    (ks,) = nodes_of(tail, "KSampler")
    assert ks["denoise"] == 0.3
    assert any(n.get("_meta", {}).get("title") == "harmonize" for n in tail.nodes.values())
    (mask_node,) = nodes_of(tail, "LoadImageMask")
    assert mask_node == {"image": "p11:local:mask", "channel": "red"}
    assert [(i.source, i.placeholder) for i in tail.inputs] == [
        ("local", "p11:local:image"),
        ("local", "p11:local:mask"),
    ]
    assert tail.models == ("realvisxl5-lightning", "sdxl-vae-fp16-fix")


def test_relight_on_a_flat_colour_has_no_tail() -> None:
    r = recipe(
        ReplaceBackground(background_colour="#224466", relight=True),
        source_image=FileRef(ref="gallery/7"),
        id="bg-flat",
    )
    (item,) = compile(r, {}, REG)
    assert isinstance(item, LocalStep) and item.engine is None


def test_compile_errors_are_plain_english() -> None:
    no_image = recipe(ReplaceBackground(background_slot="bg"), slots=BG_SLOT, id="bg-e1")
    with pytest.raises(CompileError, match="needs an input image"):
        compile(no_image, {"bg": FileRef(ref="img-bg")}, REG)
    no_bg = recipe(
        ReplaceBackground(background_slot="bg", mask_mode="manual", mask_slot="mask"),
        slots=BG_SLOT + MASK_SLOT,
        source_image=FileRef(ref="gallery/7"),
        id="bg-e2",
    )
    with pytest.raises(SlotBindingError):
        compile(no_bg, {"mask": FileRef(ref="img-m")}, REG)


# -- golden graphs -----------------------------------------------------------------------------


GOLDEN_CASES: dict[str, Any] = {
    "background__auto-photo": lambda: (
        recipe(
            ReplaceBackground(background_slot="bg"),
            slots=BG_SLOT,
            source_image=FileRef(ref="gallery/7"),
            id="golden-bg-auto",
        ),
        {"bg": FileRef(ref="img-bg")},
    ),
    "background__relight-tail": lambda: (
        recipe(
            Generate(prompt="a product on a table", aspect="1:1-1024"),
            ReplaceBackground(background_slot="bg", relight=True, relight_denoise=0.3),
            slots=BG_SLOT,
            id="golden-bg-relight",
        ),
        {"bg": FileRef(ref="img-bg")},
    ),
}


@pytest.mark.parametrize("name", sorted(GOLDEN_CASES))
def test_background_golden_graphs(name: str) -> None:
    r, bindings = GOLDEN_CASES[name]()
    items = compile(r, bindings, REG)
    graph = items[-1]
    if isinstance(graph, LocalStep):
        assert name == "background__auto-photo"  # local only: no engine graph, no golden file
        assert graph.params["feather_px"] == 8 and graph.params["fit"] == "cover"
        return
    else:
        for nid, node in graph.nodes.items():
            for value in node["inputs"].values():
                if isinstance(value, list):
                    assert value[0] in graph.nodes and value[0] != nid
        pretty = json.dumps(graph.nodes, sort_keys=True, indent=1, ensure_ascii=False) + "\n"
    path = GOLDEN / f"{name}.json"
    if os.environ.get("P11_UPDATE_GOLDEN") == "1":
        path.write_text(pretty, encoding="utf-8")
    assert path.exists(), f"missing golden {name}; run with P11_UPDATE_GOLDEN=1 and review it"
    assert path.read_text(encoding="utf-8") == pretty


def test_recompile_is_byte_identical() -> None:
    r, bindings = GOLDEN_CASES["background__relight-tail"]()
    first = [i.to_json() for i in compile(r, bindings, REG) if not isinstance(i, LocalStep)]
    for _ in range(3):
        again = [i.to_json() for i in compile(r, bindings, REG) if not isinstance(i, LocalStep)]
        assert again == first

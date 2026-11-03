"""Text overlay layout and font bundle (Phase 14, ADR-0035)."""

from __future__ import annotations

import hashlib
import io
import json

import pytest
from PIL import Image, ImageStat

from p11.media import text
from p11.media.imageio import png


def image(width: int = 1024, height: int = 1024, colour: str = "#202030") -> Image.Image:
    return Image.new("RGB", (width, height), colour)


def params(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "text": "P11",
        "font": "sans",
        "weight": "semibold",
        "size_pct": 20.0,
        "colour": "#ffffff",
        "align": "center",
        "position": "center",
        "margin_pct": 5.0,
        "letter_spacing": 0.0,
        "stroke_px": 0,
        "stroke_colour": "#000000",
        "shadow": False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------------------------
# Font bundle


def test_font_bundle_hashes_and_licences() -> None:
    """Every font P11 ships is hash-pinned and has its OFL licence text beside it."""
    directory = text.font_dir()
    data = json.loads((directory / "fonts.json").read_text())
    assert 3 <= len(data["fonts"]) <= 5
    for face in data["fonts"]:
        path = directory / face["file"]
        assert path.is_file(), face["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == face["sha256"]
        licence = (directory / face["licence"]).read_text()
        assert "SIL OPEN FONT LICENSE" in licence.upper()
        assert "Open Font License" in licence
        assert face["checked"]


def test_font_info_lists_what_the_ui_needs() -> None:
    info = text.font_info()
    assert {f["id"] for f in info} >= {"sans", "display", "serif", "condensed", "mono"}
    assert all(f["licence"] for f in info)


def test_unknown_font_is_a_plain_english_error() -> None:
    with pytest.raises(text.TextError, match="Unknown font"):
        text.load_font("comic", "bold", 40)


# ---------------------------------------------------------------------------------------------
# Layout


def test_auto_fit_shrinks_long_text_without_clipping() -> None:
    short = text.fit("sans", "bold", "P11", (800, 400), start_px=300, letter_spacing=0)
    long = text.fit("sans", "bold", "P11 STUDIO LOGO MAKER", (800, 400), start_px=300,
                    letter_spacing=0)  # fmt: skip
    assert long.size < short.size
    assert long.block_width <= 800 and long.block_height <= 400


def test_text_too_long_reports_what_to_do() -> None:
    with pytest.raises(text.TextError, match="too long"):
        text.fit("sans", "regular", "x" * 200, (100, 40), start_px=100, letter_spacing=0)


def test_multi_line_block_height_and_alignment() -> None:
    layout = text.fit("sans", "regular", "ONE\nTWO\nTHREE", (900, 900), start_px=100,
                      letter_spacing=0)  # fmt: skip
    assert len(layout.lines) == 3
    assert layout.block_height == layout.line_height * 3
    left = 100
    assert layout.x_of(layout.lines[0], left, "left") == left
    centred = layout.x_of(layout.lines[0], left, "center")
    assert centred > left
    right = layout.x_of(layout.lines[0], left, "right")
    assert right + round(layout.lines[0].width) == left + layout.block_width


@pytest.mark.parametrize(
    ("position", "check"),
    [
        ("top-left", lambda x0, y0, w, h, b: (x0, y0) == (51, 51)),
        ("bottom-right", lambda x0, y0, w, h, b: x0 + b[0] == w - 51 and y0 + b[1] == h - 51),
        ("center", lambda x0, y0, w, h, b: x0 == (w - b[0]) // 2 and y0 == (h - b[1]) // 2),
        ("top", lambda x0, y0, w, h, b: y0 == 51),
        ("right", lambda x0, y0, w, h, b: x0 + b[0] == w - 51),
    ],
)
def test_anchor_placement(position: str, check: object) -> None:
    left, top = text.place((400, 100), (1024, 1024), 5.0, position)
    assert check(left, top, 1024, 1024, (400, 100))  # type: ignore[operator]


def test_xy_places_the_block_centre() -> None:
    left, top = text.place((400, 100), (1024, 1024), 5.0, "bottom", 0.5, 0.25)
    assert left == (1024 - 400) // 2
    margin = round(1024 * 0.05)
    assert top == margin + round((1024 - 2 * margin) * 0.25) - 50


def test_placement_never_leaves_the_image() -> None:
    left, top = text.place((2000, 2000), (1024, 1024), 5.0, "center")
    assert (left, top) == (0, 0)


# ---------------------------------------------------------------------------------------------
# Rendering


def _brightness_delta(rendered: Image.Image, at: tuple[int, int, int, int]) -> float:
    return float(ImageStat.Stat(rendered.convert("L").crop(at)).mean[0])


def test_render_draws_text_and_keeps_the_size() -> None:
    base = image()
    out = text.render(base, params())
    assert out.size == base.size
    # The centre of the band where the text sits is brighter than the untouched corner.
    band = (0, 400, 1024, 620)
    assert _brightness_delta(out, band) > _brightness_delta(base, band) + 5


def test_gradient_outline_shadow_and_spacing_run() -> None:
    out = text.render(
        image(),
        params(
            text="LOGO",
            colour="#ff0000",
            colour2="#0000ff",
            stroke_px=8,
            shadow=True,
            letter_spacing=0.15,
            align="right",
            position="bottom-right",
        ),
    )
    assert out.size == (1024, 1024)
    assert out.getpixel((20, 20)) == (32, 32, 48)


def test_render_overlay_returns_a_png() -> None:
    data = text.render_overlay(png(image()), params(text="Hi"))
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(data)) as img:
        assert img.size == (1024, 1024)


def test_empty_text_is_rejected() -> None:
    with pytest.raises(text.TextError, match="Type the text"):
        text.render(image(), params(text="  \n "))

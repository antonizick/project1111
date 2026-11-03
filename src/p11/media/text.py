"""Deterministic text overlay (spec R23, Phase 14, ADR-0035).

Diffusion models render text unreliably, so logo templates have the model make the mark and put the
exact wording on top here, in Pillow, at full output resolution. Fonts are bundled SIL Open Font
License files in ``assets/fonts/`` (``fonts.json`` records each one's source, SHA-256 and licence,
checked 2026-11-03 17:00 CST); nothing is fetched at run time (S1).

Layout is pure and unit-tested: explicit lines (``\n``) are laid out at one size chosen by a binary
search that fits the text block into the printable box (``no clipping``), aligned left/centre/right,
placed by a 9-way anchor or by a draggable ``x``/``y`` point, with optional letter spacing,
gradient, outline and soft shadow. Variable fonts use Pillow's named instances for weights.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from p11.media.imageio import open_rgb, png

type Fill = float | tuple[int, ...] | str | None

#: Smallest font size P11 will shrink to before it reports the text as too long.
MIN_FONT_PX = 8
MAX_FONT_PX = 2048
#: Share of the image height the text block may use (keeps a wall of text off the edges).
MAX_BLOCK_FRACTION = 0.8


class TextError(ValueError):
    """The text cannot be drawn; the message says what to change."""


@dataclass(frozen=True)
class FontFace:
    id: str
    label: str
    file: str
    variable: bool
    weights: Mapping[str, str]
    licence: str
    source: str
    sha256: str
    checked: str


def font_dir() -> Path:
    override = os.environ.get("P11_FONTS_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "assets" / "fonts"


@lru_cache(maxsize=1)
def fonts() -> dict[str, FontFace]:
    path = font_dir() / "fonts.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise TextError(f"The bundled fonts are missing ({path}): {exc}") from None
    out: dict[str, FontFace] = {}
    for raw in data.get("fonts", []):
        face = FontFace(
            id=str(raw["id"]),
            label=str(raw["label"]),
            file=str(raw["file"]),
            variable=bool(raw.get("variable")),
            weights={str(k): str(v) for k, v in raw.get("weights", {}).items()},
            licence=str(raw.get("licence", "")),
            source=str(raw.get("source", "")),
            sha256=str(raw.get("sha256", "")),
            checked=str(raw.get("checked", "")),
        )
        out[face.id] = face
    if not out:
        raise TextError("No bundled fonts are listed in fonts.json.")
    return out


def font_info() -> list[dict[str, object]]:
    """What the UI needs: IDs, labels, available weights and licence notes."""
    return [
        {
            "id": f.id,
            "label": f.label,
            "weights": sorted(f.weights),
            "licence": f.licence,
            "source": f.source,
        }
        for f in fonts().values()
    ]


def font_path(font_id: str) -> Path:
    face = fonts().get(font_id)
    if face is None:
        raise TextError(f"Unknown font {font_id!r}. Choose one of: {', '.join(sorted(fonts()))}.")
    path = font_dir() / face.file
    if not path.is_file():
        raise TextError(f"The font file for {font_id!r} is missing ({path}).")
    return path


def load_font(font_id: str, weight: str, size: int) -> ImageFont.FreeTypeFont:
    face = fonts().get(font_id)
    if face is None:
        raise TextError(f"Unknown font {font_id!r}. Choose one of: {', '.join(sorted(fonts()))}.")
    try:
        font = ImageFont.truetype(str(font_path(font_id)), max(MIN_FONT_PX, int(size)))
    except OSError as exc:  # pragma: no cover - a damaged bundled file
        raise TextError(f"The font {font_id!r} cannot be loaded: {exc}") from None
    instance = face.weights.get(weight)
    if face.variable and instance:
        with contextlib.suppress(OSError, ValueError):
            # A font built without that named instance still draws at its default weight.
            font.set_variation_by_name(instance)
    return font


# ---------------------------------------------------------------------------------------------
# Pure layout


@dataclass(frozen=True)
class Line:
    text: str
    width: float


@dataclass(frozen=True)
class TextLayout:
    font: ImageFont.FreeTypeFont
    size: int
    spacing: int
    lines: tuple[Line, ...]
    line_height: int
    block_width: int
    block_height: int

    def x_of(self, line: Line, left: int, align: str) -> int:
        if align == "left":
            return left
        if align == "right":
            return left + self.block_width - round(line.width)
        return left + (self.block_width - round(line.width)) // 2


def _advance(font: ImageFont.FreeTypeFont, text: str, spacing: int) -> float:
    if not text:
        return 0.0
    if spacing == 0:
        return float(font.getlength(text))
    return sum(float(font.getlength(ch)) for ch in text) + spacing * (len(text) - 1)


def measure(font: ImageFont.FreeTypeFont, lines: list[str], spacing: int) -> TextLayout:
    ascent, descent = font.getmetrics()
    line_height = ascent + descent
    measured = tuple(Line(text, _advance(font, text, spacing)) for text in lines)
    width = max((line.width for line in measured), default=0.0)
    return TextLayout(
        font=font,
        size=int(font.size),
        spacing=spacing,
        lines=measured,
        line_height=line_height,
        block_width=max(1, round(width)),
        block_height=max(1, line_height * len(measured)),
    )


def split_lines(text: str) -> list[str]:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines or not any(line.strip() for line in lines):
        raise TextError("Type the text to draw on the logo.")
    return lines


def fit(
    font_id: str,
    weight: str,
    text: str,
    box: tuple[int, int],
    *,
    start_px: int,
    letter_spacing: float,
) -> TextLayout:
    """The largest size at or below ``start_px`` whose block fits ``box`` (never clips)."""
    lines = split_lines(text)
    box_w, box_h = max(1, box[0]), max(1, box[1])
    top = max(MIN_FONT_PX, min(int(start_px), MAX_FONT_PX))

    def at(size: int) -> TextLayout:
        spacing = round(letter_spacing * size)
        return measure(load_font(font_id, weight, size), lines, spacing)

    candidate = at(top)
    if candidate.block_width <= box_w and candidate.block_height <= box_h:
        return candidate
    low, high, best = MIN_FONT_PX, top, None
    while low <= high:
        middle = (low + high) // 2
        layout = at(middle)
        if layout.block_width <= box_w and layout.block_height <= box_h:
            best = layout
            low = middle + 1
        else:
            high = middle - 1
    if best is None:
        raise TextError(
            "The text is too long to fit the image even at the smallest size. "
            "Shorten it or lower the size."
        )
    return best


def place(
    block: tuple[int, int],
    image: tuple[int, int],
    margin_pct: float,
    position: str,
    x: float | None = None,
    y: float | None = None,
) -> tuple[int, int]:
    """Top-left of the block: a 9-way anchor, or the block's centre at ``x``/``y`` (0..1)."""
    block_w, block_h = block
    width, height = image
    mx = round(width * margin_pct / 100)
    my = round(height * margin_pct / 100)
    if x is not None or y is not None:
        cx = mx + round((width - 2 * mx) * (0.5 if x is None else x))
        cy = my + round((height - 2 * my) * (0.5 if y is None else y))
        left, top = cx - block_w // 2, cy - block_h // 2
    else:
        if position in ("left", "center", "right"):
            horizontal, vertical = position, "center"
        elif position in ("top", "bottom"):
            horizontal, vertical = "center", position
        else:
            vertical, _, horizontal = position.partition("-")
        left = {
            "left": mx,
            "center": (width - block_w) // 2,
            "right": width - mx - block_w,
        }[horizontal]
        top = {
            "top": my,
            "center": (height - block_h) // 2,
            "bottom": height - my - block_h,
        }[vertical]
    return (
        max(0, min(left, max(0, width - block_w))),
        max(0, min(top, max(0, height - block_h))),
    )


# ---------------------------------------------------------------------------------------------
# Drawing


def _rgba(colour: str) -> tuple[int, int, int, int]:
    try:
        raw = colour.lstrip("#")
        if len(raw) == 6:
            return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16), 255)
        if len(raw) == 8:
            return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16), int(raw[6:8], 16))
    except ValueError:
        pass
    raise TextError(f"{colour!r} is not a colour; use #rrggbb or #rrggbbaa.")


def _draw_line(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    line: Line,
    layout: TextLayout,
    *,
    fill: Fill = None,
    stroke_width: int = 0,
    stroke_fill: Fill = None,
) -> None:
    if layout.spacing == 0:
        draw.text(
            xy,
            line.text,
            font=layout.font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )
        return
    x, y = xy
    for char in line.text:
        draw.text(
            (x, y),
            char,
            font=layout.font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )
        x += round(float(layout.font.getlength(char))) + layout.spacing


def _gradient(size: tuple[int, int], top: tuple[int, int, int, int],
              bottom: tuple[int, int, int, int]) -> Image.Image:  # fmt: skip
    width, height = size
    gradient = Image.new("RGBA", (1, max(1, height)))
    pixels = gradient.load()
    assert pixels is not None
    for y in range(gradient.height):
        t = y / max(1, gradient.height - 1)
        pixels[0, y] = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True))
    return gradient.resize((max(1, width), max(1, height)), Image.Resampling.BILINEAR)


def render(image: Image.Image, params: Mapping[str, Any]) -> Image.Image:
    """Draw ``params`` over ``image`` at its full resolution and return the new image."""
    text = str(params.get("text", ""))
    font_id = str(params.get("font", "sans"))
    weight = str(params.get("weight", "semibold"))
    size_pct = float(params.get("size_pct", 12.0))
    margin_pct = float(params.get("margin_pct", 5.0))
    letter_spacing = float(params.get("letter_spacing", 0.0))
    stroke_px = int(params.get("stroke_px", 0))
    colour = _rgba(str(params.get("colour", "#ffffff")))
    gradient_end = params.get("colour2")
    stroke_colour = _rgba(str(params.get("stroke_colour", "#000000")))
    align = str(params.get("align", "center"))
    position = str(params.get("position", "bottom"))
    x = params.get("x")
    y = params.get("y")

    width, height = image.size
    mx, my = round(width * margin_pct / 100), round(height * margin_pct / 100)
    box = (max(1, width - 2 * mx), max(1, min(height - 2 * my, round(height * MAX_BLOCK_FRACTION))))
    layout = fit(
        font_id,
        weight,
        text,
        box,
        start_px=max(MIN_FONT_PX, round(height * size_pct / 100)),
        letter_spacing=letter_spacing,
    )
    left, top = place(
        (layout.block_width, layout.block_height),
        (width, height),
        margin_pct,
        position,
        None if x is None else float(x),
        None if y is None else float(y),
    )

    base = image.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    if params.get("shadow"):
        shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        for i, line in enumerate(layout.lines):
            _draw_line(
                shadow_draw,
                (layout.x_of(line, left, align), top + i * layout.line_height),
                line,
                layout,
                fill=(0, 0, 0, 150),
                stroke_width=stroke_px,
                stroke_fill=(0, 0, 0, 110),
            )
        offset = max(2, round(layout.size * 0.03))
        shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, round(layout.size * 0.02))))
        shifted = shadow.transform(
            base.size, Image.Transform.AFFINE, (1, 0, -offset, 0, 1, -offset)
        )
        base = Image.alpha_composite(base, shifted)

    if stroke_px > 0:
        for i, line in enumerate(layout.lines):
            _draw_line(
                draw,
                (layout.x_of(line, left, align), top + i * layout.line_height),
                line,
                layout,
                fill=stroke_colour,
                stroke_width=stroke_px,
                stroke_fill=stroke_colour,
            )

    if gradient_end is not None:
        mask = Image.new("L", base.size, 0)
        mask_draw = ImageDraw.Draw(mask)
        for i, line in enumerate(layout.lines):
            _draw_line(
                mask_draw,
                (layout.x_of(line, left, align), top + i * layout.line_height),
                line,
                layout,
                fill=255,
            )
        ramp = _gradient(base.size, colour, _rgba(str(gradient_end)))
        layer = Image.composite(ramp, layer, mask)
    else:
        for i, line in enumerate(layout.lines):
            _draw_line(
                draw,
                (layout.x_of(line, left, align), top + i * layout.line_height),
                line,
                layout,
                fill=colour,
            )

    out = Image.alpha_composite(base, layer)
    return out.convert("RGB") if image.mode == "RGB" else out


def render_overlay(data: bytes, params: Mapping[str, Any]) -> bytes:
    """Bytes of a PNG: ``data`` with the text drawn over it."""
    return png(render(open_rgb(data), params))


def run_text_overlay(params: Mapping[str, Any], data: Mapping[str, bytes]) -> dict[str, bytes]:
    """The ``text_overlay`` local step (ADR-0027): one PNG in, one PNG out."""
    try:
        source = data["image"]
    except KeyError:  # pragma: no cover - the compiler always supplies it
        raise TextError("The text step needs an image to draw on.") from None
    return {"image": render_overlay(source, params)}

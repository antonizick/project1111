"""Logo exports (Phase 14): transparent background, square sizes and a favicon ICO.

The transparent cut-out uses Phase 11's subject segmentation (``p11.media.segment``, manifest
``birefnet-lite``) when it is installed; otherwise — and when segmentation finds nothing — a
flat-colour key takes the background colour from the image border. Sizes are LANCZOS-resampled on a
transparent canvas; the pack is a ZIP with one PNG per size and ``favicon.ico``.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Callable, Sequence
from typing import cast

from PIL import Image, ImageChops

from p11.media.imageio import open_mask, open_rgb
from p11.media.segment import Segments

DEFAULT_SIZES: tuple[int, ...] = (512, 256, 128, 64, 32)
#: Border pixels within this channel distance of the sampled colour become transparent.
KEY_TOLERANCE = 28
#: Soft edge band above the tolerance, so a keyed logo does not look cut with scissors.
KEY_SOFTNESS = 28
_SLUG = re.compile(r"[^a-z0-9]+")


class LogoError(ValueError):
    """The logo pack cannot be made; the message says what to change."""


def _key_colour(image: Image.Image) -> tuple[int, int, int]:
    """The most common border colour (a logo is normally on one flat background)."""
    width, height = image.size
    pixels = image.load()
    assert pixels is not None
    counts: dict[tuple[int, int, int], int] = {}
    step = max(1, min(width, height) // 64)

    def note(x: int, y: int) -> None:
        pixel = pixels[x, y]
        if isinstance(pixel, tuple) and len(pixel) >= 3:
            colour = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
            counts[colour] = counts.get(colour, 0) + 1

    for x in range(0, width, step):
        for y in (0, height - 1):
            note(x, y)
    for y in range(0, height, step):
        for x in (0, width - 1):
            note(x, y)
    return max(counts, key=lambda c: counts[c])


def key_background(image: Image.Image) -> Image.Image:
    """Make the border colour transparent (flat-colour key), keeping antialiased edges soft."""
    rgb = image.convert("RGB")
    key = _key_colour(rgb)
    difference = ImageChops.difference(rgb, Image.new("RGB", rgb.size, key)).convert("L")
    # 0 at the key colour, 255 at KEY_TOLERANCE + KEY_SOFTNESS away.
    full = KEY_TOLERANCE + KEY_SOFTNESS

    def fade(value: int) -> int:
        if value <= KEY_TOLERANCE:
            return 0
        if value >= full:
            return 255
        return round((value - KEY_TOLERANCE) * 255 / KEY_SOFTNESS)

    alpha = difference.point(fade)
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def cutout(image: bytes, segmenters: Segments | None) -> Image.Image:
    """The subject on transparency: segmentation if possible, else the flat-colour key."""
    source = open_rgb(image)
    if segmenters is not None:
        try:
            mask = open_mask(segmenters.segmenter(None).mask(image))
        except Exception:
            mask = None
        if mask is not None and cast("tuple[int, int]", mask.getextrema())[1] > 8:
            out = source.convert("RGBA")
            out.putalpha(mask)
            return out
    return key_background(source)


def resize(image: Image.Image, size: int) -> Image.Image:
    """Square LANCZOS resize on a transparent canvas (never distorts the artwork)."""
    if size < 16 or size > 4096:
        raise LogoError(f"{size} is not a sensible icon size (16 to 4096 pixels).")
    copy = image.convert("RGBA")
    scale = min(size / copy.width, size / copy.height)
    resized = copy.resize(
        (max(1, round(copy.width * scale)), max(1, round(copy.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(resized, ((size - resized.width) // 2, (size - resized.height) // 2))
    return canvas


def favicon(images: Sequence[Image.Image]) -> bytes:
    if not images:
        raise LogoError("No icon sizes to put in the favicon.")
    buffer = io.BytesIO()
    images[0].save(buffer, format="ICO", sizes=[(i.width, i.height) for i in images])
    return buffer.getvalue()


def slug(text: str) -> str:
    return (_SLUG.sub("-", text.lower()).strip("-") or "logo")[:40]


def pack(
    image: bytes,
    *,
    transparent: bool = True,
    sizes: Sequence[int] = DEFAULT_SIZES,
    segmenters: Segments | None = None,
    name: str = "logo",
) -> bytes:
    """A ZIP of square PNGs plus ``favicon.ico``; transparency when asked (the default)."""
    if not sizes:
        raise LogoError("Pick at least one size.")
    base = cutout(image, segmenters) if transparent else open_rgb(image).convert("RGBA")
    made = [(int(s), resize(base, int(s))) for s in sizes]
    filename = slug(name)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for size, icon in made:
            data = io.BytesIO()
            icon.save(data, format="PNG")
            archive.writestr(f"{filename}-{size}.png", data.getvalue())
        archive.writestr("favicon.ico", favicon([icon for _, icon in made]))
    return buffer.getvalue()


Progress = Callable[[str, int, int], None]

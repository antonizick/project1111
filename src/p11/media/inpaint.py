"""Inpaint mask preparation, crop-and-stitch and paste-back (Phase 10, ADR-0025).

The job runner calls ``prepare`` before it queues an inpaint graph and ``stitch`` on the engine's
result. In between, the engine only ever sees the working image and the soft mask:

* the painted mask is resized to the image, grown by ``grow_px`` and blurred by ``blur_px`` at full
  resolution, so the blend band is the same whatever the working size;
* with ``crop`` ("only masked area at full resolution") a box around the soft mask, padded by
  ``padding_px`` for context, is cut out and scaled so small fixes are painted at the model's
  working size (``work_pixels``) and large ones fit 8 GB (``max_pixels``); without it the whole
  image is used, rounded to a multiple of 8;
* ``stitch`` scales the result back to the box and blends it over the **original** pixels with the
  soft mask, so every pixel where the soft mask is 0 is byte-for-byte the original.

The geometry functions are pure and property-tested; the image functions use Pillow only.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageFilter

from p11.media.validate import MAX_PIXELS
from p11.recipe.compile import MaskPrep

Box = tuple[int, int, int, int]
MULTIPLE = 8
#: Fixed masks saved into templates are stored at most this long on their long side.
COMPACT_SIDE = 1024


EMPTY = "The mask is empty. Paint over the part of the image you want to change."


class MaskError(ValueError):
    """The mask cannot be used; the message says what to do."""


# ---------------------------------------------------------------------------------------------
# Pure geometry


def pad_box(bbox: Box, size: tuple[int, int], padding: int) -> Box:
    """``bbox`` grown by ``padding`` on every side and clamped to an image of ``size``."""
    x0, y0, x1, y1 = bbox
    w, h = size
    return max(0, x0 - padding), max(0, y0 - padding), min(w, x1 + padding), min(h, y1 + padding)


def _round_to(value: float, multiple: int = MULTIPLE) -> int:
    return max(multiple, round(value / multiple) * multiple)


def work_size(
    box_size: tuple[int, int],
    *,
    work_pixels: int,
    max_upscale: float,
    max_pixels: int,
    upscale: bool = True,
) -> tuple[int, int]:
    """The size the engine paints a ``box_size`` region at (both sides multiples of 8).

    Smaller than ``work_pixels``: scaled up to it (at most ``max_upscale`` times) when ``upscale``.
    Larger than ``max_pixels``: scaled down to fit. Otherwise kept, rounded to a multiple of 8.
    """
    w, h = box_size
    if w <= 0 or h <= 0:
        raise ValueError("box must not be empty")
    area = w * h
    scale = 1.0
    if upscale and area < work_pixels:
        scale = min(max_upscale, math.sqrt(work_pixels / area))
    elif area > max_pixels:
        scale = math.sqrt(max_pixels / area)
    ww, hh = _round_to(w * scale), _round_to(h * scale)
    # Rounding up may push a capped size over the limit; step down until it fits.
    while ww * hh > max_pixels and (ww > MULTIPLE or hh > MULTIPLE):
        if ww >= hh:
            ww -= MULTIPLE
        else:
            hh -= MULTIPLE
    return ww, hh


# ---------------------------------------------------------------------------------------------
# Masks


def _open(data: bytes, mode: str) -> Image.Image:
    with Image.open(io.BytesIO(data)) as img:
        # Inline masks come from templates, which may be imported: cap before decoding (S8).
        if img.width * img.height > MAX_PIXELS:
            raise MaskError("The mask or image is too large to use (over 40 megapixels).")
        img.load()
        if mode == "L" and img.mode in ("RGBA", "LA"):
            # A mask with transparency: painted where it is opaque and bright.
            alpha = img.getchannel("A")
            return ImageChops.multiply(img.convert("L"), alpha)
        return img.convert(mode)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def grow(mask: Image.Image, px: int) -> Image.Image:
    """Dilate ``mask`` by about ``px`` pixels (box blur then threshold; O(1) per pixel)."""
    if px <= 0:
        return mask
    spread = mask.filter(ImageFilter.BoxBlur(px)).point(lambda v: 255 if v > 0 else 0)
    return ImageChops.lighter(mask, spread)


def soften(mask: Image.Image, px: int) -> Image.Image:
    """Feather the mask edge by a Gaussian blur of radius ``px``."""
    return mask.filter(ImageFilter.GaussianBlur(px)) if px > 0 else mask


def soft_mask(mask: Image.Image, size: tuple[int, int], grow_px: int, blur_px: int) -> Image.Image:
    if mask.size != size:
        mask = mask.resize(size, Image.Resampling.BILINEAR)
    return soften(grow(mask, grow_px), blur_px)


def check_mask(data: bytes) -> None:
    """Raise ``MaskError`` if ``data`` is not a readable mask with something painted on it."""
    try:
        mask = _open(data, "L")
    except OSError:
        raise MaskError("The mask is not a readable image. Paint it again.") from None
    if mask.getbbox() is None:
        raise MaskError(EMPTY)


def compact_mask(data: bytes) -> bytes:
    """A painted mask made small enough to store in a template (greyscale, ≤ 1024 px long side)."""
    mask = _open(data, "L")
    if max(mask.size) > COMPACT_SIDE:
        f = COMPACT_SIDE / max(mask.size)
        size = (max(1, round(mask.width * f)), max(1, round(mask.height * f)))
        mask = mask.resize(size, Image.Resampling.BILINEAR)
    buf = io.BytesIO()
    mask.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------
# Prepare and stitch


@dataclass(frozen=True)
class Prepared:
    """The working image and mask for the engine, and what ``stitch`` needs to paste back."""

    image: bytes
    mask: bytes
    box: Box
    work: tuple[int, int]
    original: Image.Image
    soft: Image.Image


def prepare(image: bytes, mask: bytes, prep: MaskPrep) -> Prepared:
    original = _open(image, "RGB")
    painted = _open(mask, "L")
    soft = soft_mask(painted, original.size, prep.grow_px, prep.blur_px)
    bbox = soft.getbbox()
    if bbox is None:
        raise MaskError(EMPTY)
    box: Box = (
        pad_box(bbox, original.size, prep.padding_px) if prep.crop else (0, 0, *original.size)
    )
    bw, bh = box[2] - box[0], box[3] - box[1]
    work = work_size(
        (bw, bh),
        work_pixels=prep.work_pixels,
        max_upscale=prep.max_upscale,
        max_pixels=prep.max_pixels,
        upscale=prep.crop,
    )
    region = original.crop(box)
    region_mask = soft.crop(box)
    if region.size != work:
        region = region.resize(work, Image.Resampling.LANCZOS)
        region_mask = region_mask.resize(work, Image.Resampling.BILINEAR)
    return Prepared(_png(region), _png(region_mask), box, work, original, soft)


def stitch(prepared: Prepared, result: bytes) -> bytes:
    """The engine's result pasted into the original image through the soft mask (PNG bytes)."""
    out = _open(result, "RGB")
    box = prepared.box
    size = (box[2] - box[0], box[3] - box[1])
    if out.size != prepared.work:
        # The VAE floors odd sizes to a multiple of 8; keep the prepared pixels for the rest.
        canvas = _open(prepared.image, "RGB")
        canvas.paste(out, (0, 0))
        out = canvas
    if out.size != size:
        out = out.resize(size, Image.Resampling.LANCZOS)
    region = prepared.original.crop(box)
    blended = Image.composite(out, region, prepared.soft.crop(box))
    final = prepared.original.copy()
    final.paste(blended, box[:2])
    return _png(final)

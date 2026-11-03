"""Opening image bytes safely (spec S8): decode caps first, then convert.

Inputs to the media steps come from uploads, gallery files and templates (imported templates are
untrusted), so every decode is capped at ``MAX_PIXELS`` before the pixel data is read.
"""

from __future__ import annotations

import io

from PIL import Image, ImageChops

from p11.media.validate import MAX_PIXELS


class ImageError(ValueError):
    """The bytes are not an image P11 can use; the message says what to do."""


def open_rgb(data: bytes) -> Image.Image:
    return _open(data, "RGB")


def open_mask(data: bytes) -> Image.Image:
    """A greyscale mask: white = painted. Alpha is folded in (painted where opaque and bright)."""
    return _open(data, "L")


def _open(data: bytes, mode: str) -> Image.Image:
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.width * img.height > MAX_PIXELS:
                raise ImageError("The image is too large to use (over 40 megapixels).")
            img.load()
            if mode == "L" and img.mode in ("RGBA", "LA"):
                alpha = img.getchannel("A")
                return ImageChops.multiply(img.convert("L"), alpha)
            return img.convert(mode)
    except OSError:
        raise ImageError("The file is not a readable picture.") from None


def png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

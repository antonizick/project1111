"""The segmentation adapter (Phase 11, ADR-0026): the stub, the factory, error messages.

The real ONNX path runs on the laptop (``make gpu-test`` and the acceptance run); here the
adapter's contracts are checked with the stub so CI stays offline and CPU-quiet.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from p11.media.segment import (
    DEFAULT_SEGMENTER_ID,
    SegmentationError,
    Segmenters,
    StubSegmenter,
)


def _size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as img:
        return img.size


def test_stub_segmenter_masks_an_ellipse_at_image_size():
    seg = StubSegmenter()
    m = seg.mask(_png((20, 10)))
    assert _size(m) == (20, 10)
    assert seg.mask(_png((20, 10))) == m  # deterministic
    img = Image.open(io.BytesIO(m)).convert("L")
    assert img.getpixel((10, 5)) == 255  # centre is subject
    assert img.getpixel((0, 0)) == 0  # corner is background


def test_stub_factory_ignores_the_model_id():
    segments = Segmenters(stub=True)
    assert segments.segmenter(None) is segments.segmenter("anything")


def test_factory_without_a_model_says_what_to_install():
    segments = Segmenters()
    with pytest.raises(SegmentationError) as exc:
        segments.segmenter(None)
    assert DEFAULT_SEGMENTER_ID in str(exc.value)
    assert "p11 models install" in str(exc.value)


def test_factory_without_the_file_says_what_to_install(tmp_path):
    segments = Segmenters(lambda mid: tmp_path / f"{mid}.onnx")
    with pytest.raises(SegmentationError) as exc:
        segments.segmenter("birefnet")
    assert "birefnet" in str(exc.value)
    assert "p11 models install" in str(exc.value)


def _png(size: tuple[int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 120, 120)).save(buf, format="PNG")
    return buf.getvalue()

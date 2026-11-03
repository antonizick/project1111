"""Subject segmentation for background replacement (Phase 11, ADR-0026).

The mask comes from a BiRefNet ONNX export run **on CPU** with ONNX Runtime inside P11: no VRAM
(the engine keeps all of it, R5), no engine start for the Background view's auto-mask, and tests
can substitute a stub. The engine-side alternative (ComfyUI's core ``RemoveBackground`` node) is
recorded in ADR-0026.

Pre- and post-processing follow the model repos' ``preprocessor_config.json`` (read at the source,
checked 2026-11-03 07:05 CST): RGB, resize to 1024x1024 bilinear, ``x/255`` then mean
[0.485, 0.456, 0.406] / std [0.229, 0.224, 0.225] (ImageNet), NCHW float32; the output is
``[1, 1, 1024, 1024]`` probabilities (sigmoid applied only if a build emits logits), resized back
to the input size. The mask is a greyscale PNG at image resolution: white = subject.

Measured on the reference laptop (i7-9750H, CPU only): BiRefNet_lite 7-8 s, BiRefNet 15-16 s per
1024x1024 image; six intra-op threads were fastest (7.3 s vs 8.2 s at eight). See
``docs/P11_BENCHMARKS.md`` → Background replacement.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

from p11.media.imageio import open_rgb, png

#: Manifest IDs (ADR-0026); the step may override with ``segmentation_model``.
DEFAULT_SEGMENTER_ID = "birefnet-lite"
INPUT_SIZE = 1024
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
THREADS = 6

INSTALL_HINT = "Install it with `p11 models install {id}`, then try again."


class SegmentationError(ValueError):
    """The subject cannot be segmented; the message says what to do."""


class Segmenter(Protocol):
    def mask(self, image: bytes) -> bytes:
        """Greyscale PNG at image resolution: white = subject, black = background."""
        ...


class Segments(Protocol):
    def segmenter(self, manifest_id: str | None) -> Segmenter:
        """The segmenter for ``manifest_id`` (``None`` = the default)."""
        ...


def _open_capped(data: bytes) -> Image.Image:
    try:
        return open_rgb(data)
    except ValueError as exc:
        raise SegmentationError(str(exc)) from None


class OnnxSegmenter:
    """BiRefNet (or its Lite variant) as an ONNX model on the CPU."""

    def __init__(self, path: Path, *, threads: int = THREADS) -> None:
        self.path = path
        self.threads = threads
        self._session = None
        self._lock = threading.Lock()

    def _load(self) -> None:
        # Imported here so tests (and the FakeEngine sandbox) never need the runtime.
        import onnxruntime as ort  # type: ignore[import-not-found]  # no stubs shipped

        so = ort.SessionOptions()
        so.intra_op_num_threads = self.threads
        try:
            self._session = ort.InferenceSession(
                str(self.path), so, providers=["CPUExecutionProvider"]
            )
        except OSError:
            raise SegmentationError(
                f"The background model file {self.path.name} cannot be read."
            ) from None
        except Exception:
            raise SegmentationError(
                f"The background model file {self.path.name} is not a usable model."
            ) from None

    def mask(self, image: bytes) -> bytes:
        img = _open_capped(image)
        x: np.ndarray = np.asarray(
            img.resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.BILINEAR), np.float32
        )
        x = x / np.float32(255.0)
        x = (x - np.array(MEAN, dtype=np.float32)) / np.array(STD, dtype=np.float32)
        x = x.transpose(2, 0, 1)[None]
        with self._lock:
            if self._session is None:
                self._load()
            assert self._session is not None
            name = self._session.get_inputs()[0].name
            (out,) = self._session.run(None, {name: x})
        y = np.asarray(out)
        while y.ndim > 2:
            y = y[0]
        if y.min() < 0.0 or y.max() > 1.0:  # a logits build: probabilities
            y = 1.0 / (1.0 + np.exp(-y))
        mask = Image.fromarray((y * 255.0).astype(np.uint8), mode="L")
        if mask.size != img.size:
            mask = mask.resize(img.size, Image.Resampling.BILINEAR)
        return png(mask)


class StubSegmenter:
    """A deterministic centred ellipse: ``p11 serve --fake`` demos and tests without the model."""

    def mask(self, image: bytes) -> bytes:
        img = _open_capped(image)
        w, h = img.size
        m = Image.new("L", (w, h), 0)
        from PIL import ImageDraw

        ImageDraw.Draw(m).ellipse(
            (w * 0.15, h * 0.05, w * 0.85, h * 0.95), fill=255, outline=255, width=max(2, w // 100)
        )
        return png(m)


class Segmenters:
    """Segmenters by manifest ID, caching ONNX sessions (one per model file)."""

    def __init__(
        self,
        resolve: Callable[[str], Path] | None = None,
        *,
        stub: bool = False,
    ) -> None:
        self._resolve = resolve
        self._stub = stub
        self._cache: dict[str, Segmenter] = {}
        self._lock = threading.Lock()

    def segmenter(self, manifest_id: str | None) -> Segmenter:
        mid = manifest_id or DEFAULT_SEGMENTER_ID
        if self._stub:
            with self._lock:
                return self._cache.setdefault("stub", StubSegmenter())
        with self._lock:
            found = self._cache.get(mid)
        if found is not None:
            return found
        if self._resolve is None:
            raise SegmentationError(
                f"The background model {mid!r} is not installed. " + INSTALL_HINT.format(id=mid)
            )
        try:
            path = self._resolve(mid)
        except Exception:
            raise SegmentationError(
                f"The background model {mid!r} is not installed. " + INSTALL_HINT.format(id=mid)
            ) from None
        if not path.is_file():
            raise SegmentationError(
                f"The background model {mid!r} is not installed. " + INSTALL_HINT.format(id=mid)
            )
        seg = OnnxSegmenter(path)
        with self._lock:
            return self._cache.setdefault(mid, seg)

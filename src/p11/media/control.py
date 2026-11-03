"""Control maps for ``pose`` steps (Phase 12, ADR-0030): pose, depth and line art, on the CPU.

The ``pose`` modifier hands its slot image to this module (``GraphInput.transform``) before the
runner uploads it to the engine: a photo becomes the map the ControlNet reads. Everything runs in
P11 on the CPU (ONNX Runtime, like the background segmenter in ``p11.media.segment``), so controls
take no VRAM from the engine and tests can substitute stubs.

- ``pose``: DWPose (YOLOX-L + RTMPose-l, Apache-2.0) finds the people and ``p11.media.pose``
  draws the OpenPose-18 skeleton picture. The pose editor sends an already-drawn picture and its
  step says ``preprocess = False``, so it skips this.
- ``depth``: Depth Anything V2 Small (Apache-2.0, 518 px, ImageNet mean/std per its
  ``preprocessor_config.json``, checked 2026-11-03 10:30 CST) → a normalised disparity map.
- ``canny``: OpenCV Canny edges (low 100, high 200), the usual ControlNet line-art input.
- ``reference``: the reference photo, resized to fit 512 px so the CLIP encoder never sees a
  multi-megapixel tensor (VRAM, R5).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

from p11.media.imageio import ImageError, open_rgb, png
from p11.media.pose import DwPose, StubPose

#: Manifest IDs of the control models (kept in step with ``p11.recipe.presets`` by a unit test).
DEFAULT_POSE_DETECTOR = "dwpose-yolox-l"
DEFAULT_POSE_ESTIMATOR = "dwpose-ll-ucoco-384"
DEFAULT_DEPTH_MODEL = "depth-anything-v2-small"

TRANSFORMS: tuple[str, ...] = ("pose", "depth", "canny", "reference")
REFERENCE_SIDE = 512
DEPTH_SIDE = 518
DEPTH_MEAN = (0.485, 0.456, 0.406)
DEPTH_STD = (0.229, 0.224, 0.225)
THREADS = 6
CANNY_LOW = 100
CANNY_HIGH = 200

INSTALL = "Install it with `p11 models install control`, then try again."


class ControlError(ValueError):
    """A control map cannot be made; the message says what to do."""


def _open(data: bytes) -> Image.Image:
    try:
        return open_rgb(data)
    except ImageError as exc:
        raise ControlError(str(exc)) from None


def canny_map(data: bytes) -> bytes:
    import cv2

    img = _open(data)
    gray = np.asarray(img.convert("L"))
    edges = cv2.Canny(gray, CANNY_LOW, CANNY_HIGH)
    return png(Image.fromarray(np.stack([edges] * 3, -1)))


def reference_image(data: bytes, side: int = REFERENCE_SIDE) -> bytes:
    """The reference photo at a size the CLIP encoder handles cheaply (aspect kept)."""
    img = _open(data)
    s = min(1.0, side / max(img.size))
    if s < 1.0:
        img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))),
                         Image.Resampling.LANCZOS)  # fmt: skip
    return png(img)


# ---------------------------------------------------------------------------------------------
# Depth


class DepthEstimator(Protocol):
    def depth_map(self, image: Image.Image) -> bytes: ...


class OnnxDepth:
    """Depth Anything V2 Small as an ONNX model, on the CPU."""

    def __init__(self, path: Path, *, threads: int = THREADS) -> None:
        self.path = path
        self.threads = threads
        self._session: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        import onnxruntime as ort  # type: ignore[import-untyped]  # no stubs shipped

        so = ort.SessionOptions()
        so.intra_op_num_threads = self.threads
        so.enable_cpu_mem_arena = False
        so.log_severity_level = 3
        try:
            self._session = ort.InferenceSession(
                str(self.path), so, providers=["CPUExecutionProvider"]
            )
        except Exception:
            raise ControlError(
                f"The depth model file {self.path.name} is not usable. {INSTALL}"
            ) from None
        return self._session

    def depth_map(self, image: Image.Image) -> bytes:
        img = image.convert("RGB")
        w, h = img.size
        scale = min(1.0, DEPTH_SIDE / max(w, h))
        # DPT takes a multiple of 14 per side and keeps the aspect ratio.
        sw = max(14, round(w * scale / 14) * 14)
        sh = max(14, round(h * scale / 14) * 14)
        resized = img.resize((sw, sh), Image.Resampling.BICUBIC)
        x: np.ndarray = np.asarray(resized, np.float32) / np.float32(255.0)
        x = (x - np.array(DEPTH_MEAN, np.float32)) / np.array(DEPTH_STD, np.float32)
        x = np.ascontiguousarray(x.transpose(2, 0, 1)[None], dtype=np.float32)
        with self._lock:
            session = self._session or self._load()
            name = session.get_inputs()[0].name
            (out,) = session.run(None, {name: x})
        y = np.asarray(out)
        while y.ndim > 2:
            y = y[0]
        lo, hi = float(y.min()), float(y.max())
        norm = (y - lo) / (hi - lo) if hi > lo else np.zeros_like(y)
        depth = Image.fromarray((norm * 255.0).astype(np.uint8), mode="L")
        if depth.size != img.size:
            depth = depth.resize(img.size, Image.Resampling.BILINEAR)
        return png(depth)


class StubDepth:
    """A top-down gradient, enough to see the control flow without the model."""

    def depth_map(self, image: Image.Image) -> bytes:
        w, h = image.convert("RGB").size
        ramp = np.tile(np.linspace(255, 0, h, dtype=np.uint8)[:, None], (1, w))
        return png(Image.fromarray(ramp, mode="L"))


# ---------------------------------------------------------------------------------------------
# The bundle the runner holds


@dataclass
class Controls:
    """Pose estimator and depth model by manifest ID; ``stub=True`` swaps in the fakes."""

    resolve: Callable[[str], Path] | None = None
    stub: bool = False
    _cache: dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _get(self, key: str, make: Callable[[], Any]) -> Any:
        with self._lock:
            found = self._cache.get(key)
        if found is None:
            found = make()
            with self._lock:
                found = self._cache.setdefault(key, found)
        return found

    def _path(self, mid: str) -> Path:
        try:
            path = self.resolve(mid) if self.resolve else None
        except Exception:
            path = None
        if path is None or not path.is_file():
            raise ControlError(f"The model {mid!r} is not installed. {INSTALL}")
        return path

    def pose(self) -> Any:
        if self.stub:
            return self._get("pose", StubPose)
        return self._get(
            DEFAULT_POSE_ESTIMATOR,
            lambda: DwPose(self._path(DEFAULT_POSE_DETECTOR), self._path(DEFAULT_POSE_ESTIMATOR)),
        )

    def depth(self) -> DepthEstimator:
        if self.stub:
            return self._get("depth", StubDepth)  # type: ignore[no-any-return]
        return self._get(  # type: ignore[no-any-return]
            DEFAULT_DEPTH_MODEL, lambda: OnnxDepth(self._path(DEFAULT_DEPTH_MODEL))
        )

    def transform(self, kind: str, data: bytes) -> bytes:
        """Apply one of ``TRANSFORMS`` to image bytes (what the runner calls before upload)."""
        from p11.media import pose as pose_media

        if kind == "pose":
            return pose_media.pose_image_from_photo(data, self.pose())
        if kind == "depth":
            return self.depth().depth_map(_open(data))
        if kind == "canny":
            return canny_map(data)
        if kind == "reference":
            return reference_image(data)
        raise ControlError(f"P11 does not know the picture preparation {kind!r}.")


__all__ = ["TRANSFORMS", "ControlError", "Controls", "canny_map", "reference_image"]

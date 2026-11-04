"""The NSFW target guard of face-swap (spec S5, ADR-0005, ADR-0028). Not a setting.

Before P11 puts a face onto an image (the image face-swap step here, every video in Phase 13) the
target is classified by **two** open classifiers, and the swap is refused when **either** says it
is sexual or nude. The swapped result is checked again before it is saved. Generation itself is
unfiltered (A5); only the face paths carry this check.

There is deliberately no flag, setting, environment variable, API field or recipe field that
turns the guard off or changes its thresholds: the models and thresholds are constants of this
module, and a missing guard model refuses the swap (it fails closed). Tests replace the whole
``FaceTools`` bundle (``p11.media.faces``) with stubs; the stub guard only ever runs with the stub
swapper, so no real swap runs without the real guard.

Classifiers (ONNX, run on the CPU in P11; hashes pinned in ``models/manifest.toml``):

- ``nsfw-marqo-384``: Marqo/nsfw-image-detection-384 (ViT-tiny, Apache-2.0), labels
  ``[NSFW, SFW]``, 384x384, mean/std 0.5. Unsafe when P(NSFW) >= 0.5 (its arg-max). Its card reports
  98.56 % accuracy on a 20 000-image test set.
- ``nsfw-freepik-eva02``: Freepik/nsfw_image_detector (EVA02-base, MIT), labels
  ``[neutral, low, medium, high]``, 448x448, CLIP mean/std. Unsafe when P(medium) + P(high) >= 0.5,
  the card's own "medium or higher" rule (low = suggestive, allowed). Its card reports 97-99.9 % per
  class, 96-100 % on AI-generated images.

Both files are FaceFusion's ONNX exports (facefusion/models-3.3.0 ``nsfw_2.onnx``, ``nsfw_3.onnx``);
pre-processing as read in FaceFusion's ``content_analyser.py`` and the model cards on 2026-11-03
10:02 CST: RGB, letterbox ("contain") to the input size, ``x/255``, mean/std, NCHW float32. Both
output logits; P11 applies the softmax.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

#: The guard's classifiers: manifest ID, input size, mean, std, unsafe classes, threshold.
MARQO_ID = "nsfw-marqo-384"
FREEPIK_ID = "nsfw-freepik-eva02"


@dataclass(frozen=True)
class ClassifierSpec:
    manifest_id: str
    size: int
    mean: tuple[float, float, float]
    std: tuple[float, float, float]
    labels: tuple[str, ...]
    unsafe: tuple[str, ...]
    threshold: float


CLASSIFIERS: tuple[ClassifierSpec, ...] = (
    ClassifierSpec(
        MARQO_ID, 384, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5), ("nsfw", "sfw"), ("nsfw",), 0.5
    ),
    ClassifierSpec(
        FREEPIK_ID,
        448,
        (0.48145466, 0.4578275, 0.40821073),
        (0.26862954, 0.26130258, 0.27577711),
        ("neutral", "low", "medium", "high"),
        ("medium", "high"),
        0.5,
    ),
)
GUARD_MODEL_IDS: tuple[str, ...] = tuple(c.manifest_id for c in CLASSIFIERS)
THREADS = 6
CACHE_SIZE = 256

#: What the user sees. Neutral on purpose: no score, no hint how to get past it.
REFUSED = "P11 does not put faces onto nude or sexual images. Choose a different target image."
REFUSED_LIKENESS = (
    "P11 does not save pictures with a person's face from a photo that look nude or sexual. "
    "Change the prompt or the image."
)
REFUSED_RESULT = "P11 does not save face swaps that look nude or sexual. Choose a different image."
MISSING = (
    "Face swap and face reference need their image check models ({ids}). Install them with "
    "`p11 models install face`, then try again."
)


class GuardRefused(ValueError):
    """The target (or the swapped result) looks sexual or nude; the swap does not happen."""


class GuardUnavailable(ValueError):
    """A guard model is missing or unreadable: face swap refuses (fails closed)."""


@dataclass(frozen=True)
class Verdict:
    unsafe: bool
    #: Unsafe probability per classifier (for tests and the benchmark log; never shown to users).
    scores: tuple[tuple[str, float], ...]


class Classifier(Protocol):
    def unsafe_probability(self, image: Image.Image) -> float: ...


class Guard(Protocol):
    def verdict(self, image: Image.Image) -> Verdict: ...


def letterbox(img: Image.Image, size: int) -> Image.Image:
    """Fit ``img`` inside ``size``x``size`` keeping its aspect, padded with black (contain)."""
    scale = size / max(img.width, img.height)
    w, h = max(1, round(img.width * scale)), max(1, round(img.height * scale))
    canvas = Image.new("RGB", (size, size))
    canvas.paste(
        img.convert("RGB").resize((w, h), Image.Resampling.BILINEAR),
        ((size - w) // 2, (size - h) // 2),
    )
    return canvas


def softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return np.asarray(e / e.sum())


def tensor(img: Image.Image, spec: ClassifierSpec) -> np.ndarray:
    x: np.ndarray = np.asarray(letterbox(img, spec.size), np.float32) / np.float32(255.0)
    x = (x - np.array(spec.mean, np.float32)) / np.array(spec.std, np.float32)
    return np.ascontiguousarray(x.transpose(2, 0, 1)[None], dtype=np.float32)


def unsafe_from_logits(logits: np.ndarray, spec: ClassifierSpec) -> float:
    probs = softmax(np.asarray(logits, np.float64).reshape(-1))
    if probs.shape[0] != len(spec.labels):
        raise GuardUnavailable(f"The image check model {spec.manifest_id} has the wrong outputs.")
    return float(sum(probs[spec.labels.index(label)] for label in spec.unsafe))


class OnnxClassifier:
    def __init__(self, path: Path, spec: ClassifierSpec, *, threads: int = THREADS) -> None:
        self.path = path
        self.spec = spec
        self.threads = threads
        self._session = None
        self._lock = threading.Lock()

    def _load(self) -> None:
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
            raise GuardUnavailable(
                f"The image check model file {self.path.name} is not usable. "
                "Reinstall it with `p11 models install face`."
            ) from None

    def unsafe_probability(self, image: Image.Image) -> float:
        x = tensor(image, self.spec)
        with self._lock:
            if self._session is None:
                self._load()
            assert self._session is not None
            name = self._session.get_inputs()[0].name
            (out,) = self._session.run(None, {name: x})
        return unsafe_from_logits(np.asarray(out), self.spec)


class NsfwGuard:
    """Both classifiers; unsafe when either crosses its threshold. Verdicts cached by content."""

    def __init__(self, classifiers: dict[str, Classifier]) -> None:
        missing = [c.manifest_id for c in CLASSIFIERS if c.manifest_id not in classifiers]
        if missing:
            raise GuardUnavailable(MISSING.format(ids=", ".join(missing)))
        self._classifiers = classifiers
        self._cache: OrderedDict[bytes, Verdict] = OrderedDict()
        self._lock = threading.Lock()

    def verdict(self, image: Image.Image) -> Verdict:
        rgb = image.convert("RGB")
        key = hashlib.sha256(
            rgb.width.to_bytes(4, "big") + rgb.height.to_bytes(4, "big") + rgb.tobytes()
        ).digest()
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return hit
        scores = []
        unsafe = False
        for spec in CLASSIFIERS:
            p = self._classifiers[spec.manifest_id].unsafe_probability(rgb)
            scores.append((spec.manifest_id, round(p, 4)))
            unsafe = unsafe or p >= spec.threshold
        v = Verdict(unsafe, tuple(scores))
        with self._lock:
            self._cache[key] = v
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return v


def build_guard(resolve: Callable[[str], Path] | None) -> NsfwGuard:
    """The real guard from installed manifest models; raises ``GuardUnavailable`` if any is gone."""
    classifiers: dict[str, Classifier] = {}
    missing = []
    for spec in CLASSIFIERS:
        try:
            path = resolve(spec.manifest_id) if resolve else None
        except Exception:
            path = None
        if path is None or not path.is_file():
            missing.append(spec.manifest_id)
            continue
        classifiers[spec.manifest_id] = OnnxClassifier(path, spec)
    if missing:
        raise GuardUnavailable(MISSING.format(ids=", ".join(missing)))
    return NsfwGuard(classifiers)


def check_target(guard: Guard, image: Image.Image) -> None:
    """Refuse the swap when the target looks sexual or nude."""
    if guard.verdict(image).unsafe:
        raise GuardRefused(REFUSED)


def check_result(guard: Guard, image: Image.Image) -> None:
    """Refuse to save a swapped image that looks sexual or nude."""
    if guard.verdict(image).unsafe:
        raise GuardRefused(REFUSED_RESULT)


def check_likeness(guard: Guard, image: Image.Image) -> None:
    """Refuse to save a picture that carries a real face (reference, or an edit of a swap) and
    looks sexual or nude (ADR-0037)."""
    if guard.verdict(image).unsafe:
        raise GuardRefused(REFUSED_LIKENESS)


# ---------------------------------------------------------------------------------------------
# Stub for ``p11 serve --fake`` and tests (paired only with the stub swapper, ``p11.media.faces``)

#: The stub's "unsafe" marker: a synthetic test image whose four corner pixels are pure magenta.
STUB_MARKER = (255, 0, 255)


class StubGuard:
    """Unsafe exactly when all four corner pixels are ``STUB_MARKER`` (synthetic test images)."""

    def verdict(self, image: Image.Image) -> Verdict:
        rgb = image.convert("RGB")
        w, h = rgb.size
        corners = [rgb.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
        unsafe = all(c == STUB_MARKER for c in corners)
        return Verdict(unsafe, (("stub", 1.0 if unsafe else 0.0),))

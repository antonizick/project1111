"""Face detection, swap and restoration on the CPU inside P11 (Phase 12, ADR-0011, ADR-0029).

The ``face_swap`` and ``face_restore`` local steps run here (ADR-0027), on ONNX Runtime like the
background segmenter: no VRAM is taken from the engine (R5) and no ComfyUI custom node is needed
(S3). The pipeline is the InsightFace one that ReActor and FaceFusion also wrap:

1. **Guard first** (``p11.media.nsfw``, S5): the target image is classified before anything else
   and the swap is refused if it looks sexual or nude; the result is checked again.
2. **Detect** faces with YuNet (OpenCV Zoo, MIT) through ``cv2.FaceDetectorYN``: box, five landmarks
   (eyes, nose, mouth corners, image-left first) and a score. Faces are ordered largest first;
   ``*_face_index`` picks from that order (0 = largest, the "auto" choice).
3. **Embed** the source face with ArcFace w600k-r50 (InsightFace ``buffalo_l``): five-point
   similarity alignment to the ArcFace 112x112 template, ``x/127.5 - 1``, RGB, L2-normalised 512-d.
4. **Swap** with ``inswapper_128`` (InsightFace): the target face aligned to the same template at
   128x128, ``x/255`` RGB; latent = normalised embedding x ``emap`` (the model's last initializer),
   re-normalised, as InsightFace's reference ``INSwapper.get`` does; output RGB in [0, 1].
5. **Restore** (optional) with GFPGAN v1.4 (Apache-2.0): FFHQ 512x512 alignment,
   ``(x/255-0.5)/0.5``,
   output in [-1, 1], blended by ``visibility``.
6. **Paste back** through the inverse affine with a feathered box mask, only inside the face's
   bounding area, so the rest of the image keeps its exact pixels.

Templates and normalisation were read at the source on 2026-11-03 10:06 CST: InsightFace
``model_zoo/inswapper.py`` (reference swapper), FaceFusion ``face_helper.py`` (``arcface_112_v2``,
``ffhq_512`` warp templates), ``face_recognizer.py`` and ``face_enhancer/core.py``. The ONNX files
are FaceFusion's re-hosted exports (facefusion/models-3.0.0), hash-pinned in the manifest;
InsightFace's swapper and recogniser weights are **non-commercial** (flagged, R11).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image, ImageDraw

from p11.media.imageio import ImageError, open_rgb, png
from p11.media.nsfw import (
    Guard,
    GuardUnavailable,
    StubGuard,
    build_guard,
    check_result,
    check_target,
)

DETECTOR_ID = "yunet-2023mar"
RECOGNIZER_ID = "arcface-w600k-r50"
SWAPPER_ID = "inswapper-128"
RESTORER_ID = "gfpgan-1.4"
THREADS = 6

#: Five-point templates, normalised to the crop size (x right, y down; image-left eye first).
ARCFACE_TEMPLATE = np.array(
    [
        [0.34191607, 0.46157411],
        [0.65653393, 0.45983393],
        [0.50022500, 0.64050536],
        [0.37097589, 0.82469196],
        [0.63151696, 0.82325089],
    ],
    np.float64,
)
FFHQ_TEMPLATE = np.array(
    [
        [0.37691676, 0.46864664],
        [0.62285697, 0.46912813],
        [0.50123859, 0.61331904],
        [0.39308822, 0.72541100],
        [0.61150205, 0.72490465],
    ],
    np.float64,
)
#: YuNet's working sizes (it is trained on faces of ~10-300 px): detect at both, merge.
DETECT_SIDES = (640, 320)
DETECT_SCORE = 0.6
NMS_IOU = 0.4
#: Feather of the paste-back mask, as a fraction of the crop size.
MASK_BLUR = 0.3
MASK_PADDING = 0.04

NO_FACE_SOURCE = "P11 found no face in the face photo. Use a clear, front-facing photo of one face."
NO_FACE_TARGET = "P11 found no face in the target image to swap onto."
NO_FACE_RESTORE = "P11 found no face to restore in this image."
INSTALL = "Install it with `p11 models install face`, then try again."


class FaceError(ValueError):
    """The face step cannot run on these images; the message says what to do."""


# ---------------------------------------------------------------------------------------------
# Pure geometry


@dataclass(frozen=True)
class Face:
    """A detected face in image pixels: box ``(x1, y1, x2, y2)``, five landmarks, score."""

    box: tuple[float, float, float, float]
    landmarks: tuple[tuple[float, float], ...]
    score: float

    @property
    def area(self) -> float:
        return max(0.0, self.box[2] - self.box[0]) * max(0.0, self.box[3] - self.box[1])

    def scaled(self, s: float) -> Face:
        return Face(
            (self.box[0] * s, self.box[1] * s, self.box[2] * s, self.box[3] * s),
            tuple((x * s, y * s) for x, y in self.landmarks),
            self.score,
        )

    def to_json(self, width: int, height: int) -> dict[str, Any]:
        """Box normalised to the image (for the UI's click-to-pick overlay)."""
        x1, y1, x2, y2 = self.box
        return {
            "box": [
                round(max(0.0, x1) / width, 4),
                round(max(0.0, y1) / height, 4),
                round(min(float(width), x2) / width, 4),
                round(min(float(height), y2) / height, 4),
            ],
            "score": round(self.score, 3),
        }


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def merge_faces(faces: list[Face], threshold: float = NMS_IOU) -> list[Face]:
    """Non-maximum suppression across detection passes: keep the best-scoring of overlaps."""
    kept: list[Face] = []
    for f in sorted(faces, key=lambda f: -f.score):
        if all(iou(f.box, k.box) < threshold for k in kept):
            kept.append(f)
    return kept


def order_faces(faces: list[Face]) -> list[Face]:
    """Largest first; ties left to right (index 0 = the "auto" choice)."""
    return sorted(faces, key=lambda f: (-round(f.area, 3), f.box[0], f.box[1]))


def pick(faces: list[Face], index: int, *, none: str, what: str) -> Face:
    faces = order_faces(faces)
    if not faces:
        raise FaceError(none)
    if index >= len(faces):
        raise FaceError(
            f"The {what} has {len(faces)} face{'s' if len(faces) != 1 else ''}; "
            f"face {index + 1} does not exist. Pick one of the faces shown."
        )
    return faces[index]


def similarity_transform(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Least-squares similarity (rotation, uniform scale, shift) mapping ``src`` onto ``dst``.

    Umeyama's method; returns the 2x3 affine matrix. Pure numpy, deterministic.
    """
    src = np.asarray(src, np.float64)
    dst = np.asarray(dst, np.float64)
    mu_s, mu_d = src.mean(0), dst.mean(0)
    s, d = src - mu_s, dst - mu_d
    cov = d.T @ s / len(src)
    u, sig, vt = np.linalg.svd(cov)
    sign = np.eye(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sign[1, 1] = -1
    r = u @ sign @ vt
    var = (s**2).sum() / len(src)
    scale = float(np.trace(np.diag(sig) @ sign) / var) if var > 0 else 1.0
    t = mu_d - scale * r @ mu_s
    return np.hstack([scale * r, t[:, None]])


def align_matrix(face: Face, template: np.ndarray, size: int) -> np.ndarray:
    return similarity_transform(np.array(face.landmarks), template * size)


def invert_affine(m: np.ndarray) -> np.ndarray:
    full = np.vstack([m, [0.0, 0.0, 1.0]])
    return np.asarray(np.linalg.inv(full)[:2])


def box_mask(size: int, blur: float = MASK_BLUR, padding: float = MASK_PADDING) -> np.ndarray:
    """A feathered rectangle over the crop (float32 0..1), as the swap/restore paste-back mask."""
    import cv2

    blur_px = int(size * 0.5 * blur)
    edge = max(blur_px // 2, 1, int(size * padding))
    m = np.zeros((size, size), np.float32)
    m[edge:-edge, edge:-edge] = 1.0
    if blur_px > 0:
        m = np.asarray(cv2.GaussianBlur(m, (0, 0), blur_px * 0.25), np.float32)
    return m


def warp(image: np.ndarray, m: np.ndarray, size: int) -> np.ndarray:
    import cv2

    return cv2.warpAffine(
        image, m, (size, size), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
    )


def paste_back(
    image: np.ndarray, crop: np.ndarray, mask: np.ndarray, m: np.ndarray, amount: float = 1.0
) -> np.ndarray:
    """Blend ``crop`` (aligned with ``m``) back into ``image`` inside the mapped crop area only."""
    import cv2

    h, w = image.shape[:2]
    size = crop.shape[0]
    inv = invert_affine(m)
    corners = np.array([[0, 0, 1], [size, 0, 1], [0, size, 1], [size, size, 1]], np.float64)
    pts = corners @ inv.T
    x1 = int(max(0, np.floor(pts[:, 0].min())))
    y1 = int(max(0, np.floor(pts[:, 1].min())))
    x2 = int(min(w, np.ceil(pts[:, 0].max())))
    y2 = int(min(h, np.ceil(pts[:, 1].max())))
    if x2 <= x1 or y2 <= y1:
        return image
    local = inv.copy()
    local[:, 2] -= (x1, y1)
    region = (x2 - x1, y2 - y1)
    back = cv2.warpAffine(
        crop, local, region, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
    )
    alpha = cv2.warpAffine(mask, local, region, flags=cv2.INTER_LINEAR, borderValue=0.0)
    alpha = np.clip(alpha * float(amount), 0.0, 1.0)[..., None]
    out = image.copy()
    patch = out[y1:y2, x1:x2].astype(np.float32)
    patch = patch * (1.0 - alpha) + back.astype(np.float32) * alpha
    out[y1:y2, x1:x2] = np.clip(np.rint(patch), 0, 255).astype(np.uint8)
    return out


# ---------------------------------------------------------------------------------------------
# Model adapters


class Detector(Protocol):
    def detect(self, rgb: np.ndarray) -> list[Face]: ...


class Recognizer(Protocol):
    def embedding(self, rgb: np.ndarray, face: Face) -> np.ndarray: ...


class Swapper(Protocol):
    def swap(
        self, rgb: np.ndarray, face: Face, embedding: np.ndarray, amount: float
    ) -> np.ndarray: ...


class Restorer(Protocol):
    def restore(self, rgb: np.ndarray, face: Face, visibility: float) -> np.ndarray: ...


def _session(path: Path, what: str, threads: int = THREADS) -> Any:
    import onnxruntime as ort  # type: ignore[import-untyped]  # no stubs shipped

    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.enable_cpu_mem_arena = False
    so.log_severity_level = 3
    try:
        return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
    except Exception:
        raise FaceError(f"The {what} model file {path.name} is not usable. {INSTALL}") from None


class _Lazy:
    def __init__(self, path: Path, what: str) -> None:
        self.path = path
        self.what = what
        self._session: Any = None
        self._lock = threading.Lock()

    def run(self, feeds: Mapping[str, np.ndarray]) -> list[np.ndarray]:
        with self._lock:
            if self._session is None:
                self._session = _session(self.path, self.what)
            return list(self._session.run(None, dict(feeds)))


class YuNetDetector:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._det: Any = None

    def _detector(self, size: tuple[int, int]) -> Any:
        import cv2

        if self._det is None:
            # OpenCV 5's DNN engine logs a harmless "targets not supported" warning per load.
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
            try:
                self._det = cv2.FaceDetectorYN.create(
                    str(self.path), "", size, DETECT_SCORE, 0.3, 5000
                )
            except cv2.error:
                raise FaceError(
                    f"The face detector file {self.path.name} is not usable. {INSTALL}"
                ) from None
        self._det.setInputSize(size)
        return self._det

    def detect(self, rgb: np.ndarray) -> list[Face]:
        import cv2

        h, w = rgb.shape[:2]
        bgr = np.ascontiguousarray(rgb[..., ::-1])
        found: list[Face] = []
        with self._lock:
            for side in DETECT_SIDES:
                s = min(1.0, side / max(w, h))
                sw, sh = max(1, round(w * s)), max(1, round(h * s))
                small = cv2.resize(bgr, (sw, sh), interpolation=cv2.INTER_AREA) if s < 1 else bgr
                _, rows = self._detector((sw, sh)).detect(small)
                for r in rows if rows is not None else []:
                    x, y, bw, bh = (float(v) for v in r[:4])
                    kps = tuple((float(r[4 + 2 * i]), float(r[5 + 2 * i])) for i in range(5))
                    found.append(Face((x, y, x + bw, y + bh), kps, float(r[14])).scaled(1 / s))
                if s >= 1:
                    break
        return order_faces(merge_faces(found))


class ArcFaceRecognizer:
    def __init__(self, path: Path) -> None:
        self.model = _Lazy(path, "face recognition")

    def embedding(self, rgb: np.ndarray, face: Face) -> np.ndarray:
        crop = warp(rgb, align_matrix(face, ARCFACE_TEMPLATE, 112), 112).astype(np.float32)
        x = (crop / np.float32(127.5) - np.float32(1.0)).transpose(2, 0, 1)[None]
        (out,) = self.model.run({"input": np.ascontiguousarray(x)})
        v = np.asarray(out, np.float64).reshape(-1)
        n = np.linalg.norm(v)
        if not np.isfinite(n) or n == 0:
            raise FaceError(NO_FACE_SOURCE)
        return v / n


class InSwapper:
    SIZE = 128

    def __init__(self, path: Path) -> None:
        self.path = path
        self.model = _Lazy(path, "face swap")
        self._emap: np.ndarray | None = None
        self._lock = threading.Lock()

    def emap(self) -> np.ndarray:
        with self._lock:
            if self._emap is None:
                import onnx
                from onnx import numpy_helper

                try:
                    graph = onnx.load(str(self.path), load_external_data=False).graph
                    self._emap = np.asarray(numpy_helper.to_array(graph.initializer[-1]))
                except Exception:
                    raise FaceError(
                        f"The face swap model file {self.path.name} is not usable. {INSTALL}"
                    ) from None
                if self._emap.shape != (512, 512):
                    raise FaceError(f"The face swap model {self.path.name} is not inswapper_128.")
            return self._emap

    def swap(self, rgb: np.ndarray, face: Face, embedding: np.ndarray, amount: float) -> np.ndarray:
        m = align_matrix(face, ARCFACE_TEMPLATE, self.SIZE)
        crop = warp(rgb, m, self.SIZE)
        x = (crop.astype(np.float32) / np.float32(255.0)).transpose(2, 0, 1)[None]
        latent = embedding.reshape(1, -1) @ self.emap()
        latent = latent / np.linalg.norm(latent)
        (out,) = self.model.run(
            {"target": np.ascontiguousarray(x), "source": latent.astype(np.float32)}
        )
        swapped = np.clip(np.asarray(out)[0].transpose(1, 2, 0), 0.0, 1.0) * 255.0
        return paste_back(rgb, swapped.astype(np.float32), box_mask(self.SIZE), m, amount)


class GfpganRestorer:
    SIZE = 512

    def __init__(self, path: Path) -> None:
        self.model = _Lazy(path, "face restore")

    def restore(self, rgb: np.ndarray, face: Face, visibility: float) -> np.ndarray:
        m = align_matrix(face, FFHQ_TEMPLATE, self.SIZE)
        crop = warp(rgb, m, self.SIZE).astype(np.float32)
        x = ((crop / np.float32(255.0) - 0.5) / 0.5).transpose(2, 0, 1)[None]
        (out,) = self.model.run({"input": np.ascontiguousarray(x, dtype=np.float32)})
        restored = (np.clip(np.asarray(out)[0], -1.0, 1.0) + 1.0) / 2.0 * 255.0
        restored = restored.transpose(1, 2, 0)
        return paste_back(rgb, restored.astype(np.float32), box_mask(self.SIZE), m, visibility)


# ---------------------------------------------------------------------------------------------
# Stubs for ``p11 serve --fake`` and tests: no models, visible but fake results


class StubDetector:
    """One face in the upper middle of any image (a portrait's usual spot)."""

    def detect(self, rgb: np.ndarray) -> list[Face]:
        h, w = rgb.shape[:2]
        side = 0.3 * min(w, h)
        cx, cy = w / 2, h * 0.38
        box = (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
        kps = tuple(
            (box[0] + float(px) * side, box[1] + float(py) * side) for px, py in ARCFACE_TEMPLATE
        )
        return [Face(box, kps, 0.99)]


class StubRecognizer:
    def embedding(self, rgb: np.ndarray, face: Face) -> np.ndarray:
        x1, y1, x2, y2 = (int(v) for v in face.box)
        mean = rgb[max(0, y1) : y2, max(0, x1) : x2].reshape(-1, 3).mean(0)
        return np.concatenate([mean / 255.0, np.zeros(509)])


class StubSwapper:
    """Fills the face box with the source's mean colour: shows where a swap would land."""

    def swap(self, rgb: np.ndarray, face: Face, embedding: np.ndarray, amount: float) -> np.ndarray:
        img = Image.fromarray(rgb)
        colour = tuple(int(c * 255) for c in embedding[:3])
        overlay = img.copy()
        ImageDraw.Draw(overlay).ellipse(face.box, fill=colour)
        return np.asarray(Image.blend(img, overlay, float(amount) * 0.8))


class StubRestorer:
    def restore(self, rgb: np.ndarray, face: Face, visibility: float) -> np.ndarray:
        img = Image.fromarray(rgb)
        overlay = img.copy()
        ImageDraw.Draw(overlay).rectangle(face.box, outline=(255, 255, 255), width=3)
        return np.asarray(Image.blend(img, overlay, float(visibility)))


# ---------------------------------------------------------------------------------------------
# The bundle the runner holds


class FaceKitProtocol(Protocol):
    def guard(self) -> Guard: ...
    def detector(self) -> Detector: ...
    def recognizer(self) -> Recognizer: ...
    def swapper(self, manifest_id: str | None) -> Swapper: ...
    def restorer(self, manifest_id: str | None) -> Restorer: ...


@dataclass
class FaceKit:
    """Face models by manifest ID with cached sessions; ``stub=True`` swaps in the fakes.

    The stub mode replaces every part at once (guard included), so the real swapper never runs
    without the real guard.
    """

    resolve: Callable[[str], Path] | None = None
    stub: bool = False
    _cache: dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _path(self, mid: str, what: str) -> Path:
        try:
            path = self.resolve(mid) if self.resolve else None
        except Exception:
            path = None
        if path is None or not path.is_file():
            raise FaceError(f"The {what} model {mid!r} is not installed. {INSTALL}")
        return path

    def _get(self, key: str, make: Callable[[], Any]) -> Any:
        with self._lock:
            found = self._cache.get(key)
        if found is None:
            found = make()
            with self._lock:
                found = self._cache.setdefault(key, found)
        return found

    def guard(self) -> Guard:
        if self.stub:
            return self._get("guard", StubGuard)  # type: ignore[no-any-return]
        return self._get("guard", lambda: build_guard(self.resolve))  # type: ignore[no-any-return]

    def detector(self) -> Detector:
        if self.stub:
            return self._get("detect", StubDetector)  # type: ignore[no-any-return]
        return self._get(  # type: ignore[no-any-return]
            DETECTOR_ID, lambda: YuNetDetector(self._path(DETECTOR_ID, "face detection"))
        )

    def recognizer(self) -> Recognizer:
        if self.stub:
            return self._get("recognize", StubRecognizer)  # type: ignore[no-any-return]
        return self._get(  # type: ignore[no-any-return]
            RECOGNIZER_ID,
            lambda: ArcFaceRecognizer(self._path(RECOGNIZER_ID, "face recognition")),
        )

    def swapper(self, manifest_id: str | None) -> Swapper:
        if self.stub:
            return self._get("swap", StubSwapper)  # type: ignore[no-any-return]
        mid = manifest_id or SWAPPER_ID
        return self._get(mid, lambda: InSwapper(self._path(mid, "face swap")))  # type: ignore[no-any-return]

    def restorer(self, manifest_id: str | None) -> Restorer:
        if self.stub:
            return self._get("restore", StubRestorer)  # type: ignore[no-any-return]
        mid = manifest_id or RESTORER_ID
        return self._get(mid, lambda: GfpganRestorer(self._path(mid, "face restore")))  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------------------------
# Local-step operations (``p11.jobs.runner``) and the Face view's helpers


def _rgb(data: bytes, what: str) -> Image.Image:
    try:
        return open_rgb(data)
    except ImageError as exc:
        raise FaceError(f"The {what}: {exc}") from None


def detect_faces(image: bytes, kit: FaceKitProtocol) -> tuple[list[Face], tuple[int, int]]:
    """Faces in an image, largest first (the Face view's click-to-pick overlay)."""
    img = _rgb(image, "image")
    return kit.detector().detect(np.asarray(img)), img.size


def run_face_swap(
    params: Mapping[str, Any], inputs: Mapping[str, bytes], kit: FaceKitProtocol
) -> dict[str, bytes]:
    """The ``face_swap`` local step. Inputs: ``image`` (target) and ``face`` (source photo).

    The guard runs before anything else and again on the result (S5); neither can be skipped.
    """
    target = _rgb(inputs["image"], "target image")
    guard = kit.guard()  # GuardUnavailable when a guard model is missing: fail closed
    check_target(guard, target)
    source = np.asarray(_rgb(inputs["face"], "face photo"))
    tgt = np.asarray(target)
    detector = kit.detector()
    src_face = pick(
        detector.detect(source),
        int(params.get("source_face_index", 0)),
        none=NO_FACE_SOURCE,
        what="face photo",
    )
    tgt_face = pick(
        detector.detect(tgt),
        int(params.get("target_face_index", 0)),
        none=NO_FACE_TARGET,
        what="target image",
    )
    embedding = kit.recognizer().embedding(source, src_face)
    out = kit.swapper(params.get("swapper_model")).swap(
        tgt, tgt_face, embedding, float(params.get("blend", 1.0))
    )
    if params.get("restore", True):
        visibility = float(params.get("restore_visibility", 1.0))
        if visibility > 0:
            out = kit.restorer(params.get("restore_model")).restore(out, tgt_face, visibility)
    result = Image.fromarray(out)
    check_result(guard, result)
    return {"image": png(result)}


def run_face_restore(
    params: Mapping[str, Any], inputs: Mapping[str, bytes], kit: FaceKitProtocol
) -> dict[str, bytes]:
    """The ``face_restore`` local step: GFPGAN on every face (or one, by ``face_index``)."""
    img = np.asarray(_rgb(inputs["image"], "image"))
    faces = kit.detector().detect(img)
    if not faces:
        raise FaceError(NO_FACE_RESTORE)
    index = params.get("face_index")
    chosen = (
        faces if index is None else [pick(faces, int(index), none=NO_FACE_RESTORE, what="image")]
    )
    restorer = kit.restorer(params.get("restore_model"))
    visibility = float(params.get("visibility", 1.0))
    for face in chosen:
        img = restorer.restore(img, face, visibility)
    return {"image": png(Image.fromarray(img))}


__all__ = [
    "FaceError",
    "FaceKit",
    "GuardUnavailable",
    "detect_faces",
    "run_face_restore",
    "run_face_swap",
]

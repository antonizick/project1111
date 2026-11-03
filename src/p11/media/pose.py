"""Body poses for ControlNet (Phase 12, ADR-0030): skeleton model, renderer, DWPose extraction.

A pose is a list of people; a person is 18 OpenPose (COCO-18) keypoints, each ``(x, y)``
normalised to the image (0..1) or ``None`` when not visible. The same JSON comes from the pose
editor in the Face & Pose view and from ``extract`` (a photo), and ``render`` turns it into the
OpenPose control image the union ControlNet reads: black background, limbs as coloured ellipses
dimmed to 60 %, joints as coloured dots.

The drawing convention (limb pairs, 18 colours, stick width 4 at 512 px, 60 % limb dim) and the
DWPose pipeline were read at the source on 2026-11-03 10:14 CST: ``draw_bodypose`` in
huggingface/controlnet_aux ``dwpose/util.py`` and IDEA-Research/DWPose
``ControlNet-v1-1-nightly/annotator/dwpose/{onnxdet,onnxpose,wholebody}.py`` (all Apache-2.0).
DWPose = YOLOX-L person detection (640x640 letterbox, pad 114, raw 0..255, score > 0.3, NMS 0.45)
then RTMPose-l whole-body (288x384 crop of the box padded x1.25, ImageNet mean/std, SimCC split
ratio 2), body keypoints mapped to OpenPose order with the neck = mid-shoulders.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from p11.media.imageio import ImageError, open_rgb, png

DETECTOR_ID = "dwpose-yolox-l"
ESTIMATOR_ID = "dwpose-ll-ucoco-384"
THREADS = 6

KEYPOINTS: tuple[str, ...] = (
    "nose", "neck",
    "right_shoulder", "right_elbow", "right_wrist",
    "left_shoulder", "left_elbow", "left_wrist",
    "right_hip", "right_knee", "right_ankle",
    "left_hip", "left_knee", "left_ankle",
    "right_eye", "left_eye", "right_ear", "left_ear",
)  # fmt: skip
#: Limbs as 0-based keypoint pairs, in drawing order (the first 17 of OpenPose's 19 are drawn).
LIMBS: tuple[tuple[int, int], ...] = (
    (1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10),
    (1, 11), (11, 12), (12, 13), (1, 0), (0, 14), (14, 16), (0, 15), (15, 17),
)  # fmt: skip
COLOURS: tuple[tuple[int, int, int], ...] = (
    (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0),
    (0, 255, 0), (0, 255, 85), (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255),
    (0, 0, 255), (85, 0, 255), (170, 0, 255), (255, 0, 255), (255, 0, 170), (255, 0, 85),
)  # fmt: skip
#: Left/right keypoint pairs (mirror swaps them).
MIRROR_PAIRS: tuple[tuple[int, int], ...] = ((2, 5), (3, 6), (4, 7), (8, 11), (9, 12), (10, 13),
                                             (14, 15), (16, 17))  # fmt: skip
#: COCO-wholebody body index for each OpenPose keypoint (``-1`` = neck, the shoulders' mean).
OPENPOSE_FROM_COCO: tuple[int, ...] = (0, -1, 6, 8, 10, 5, 7, 9, 12, 14, 16, 11, 13, 15, 2, 1, 4, 3)
MIN_SCORE = 0.3
MAX_PEOPLE = 8
MAX_RENDER_SIDE = 2048

Point = tuple[float, float] | None
Person = tuple[Point, ...]

NO_PERSON = "P11 found no person in this photo. Use a photo where the whole body is visible."


class PoseError(ValueError):
    """The pose cannot be read or drawn; the message says what to do."""


# ---------------------------------------------------------------------------------------------
# Pure: validation, mirror, rendering


def parse_people(raw: Any) -> list[Person]:
    """Validate pose JSON (``[[[x, y] | null] * 18, ...]``) into people."""
    if not isinstance(raw, list) or not raw:
        raise PoseError("The pose has no people. Add a person or pick a stock pose.")
    if len(raw) > MAX_PEOPLE:
        raise PoseError(f"A pose can have at most {MAX_PEOPLE} people.")
    people: list[Person] = []
    for person in raw:
        if not isinstance(person, list) or len(person) != len(KEYPOINTS):
            raise PoseError(f"Each person needs {len(KEYPOINTS)} keypoints (OpenPose order).")
        points: list[Point] = []
        for p in person:
            if p is None:
                points.append(None)
                continue
            if (
                not isinstance(p, list | tuple)
                or len(p) != 2
                or not all(isinstance(v, int | float) and math.isfinite(v) for v in p)
            ):
                raise PoseError("A keypoint must be [x, y] (0 to 1) or null.")
            x, y = float(p[0]), float(p[1])
            if not (-0.5 <= x <= 1.5 and -0.5 <= y <= 1.5):
                raise PoseError("A keypoint is far outside the picture.")
            points.append((x, y))
        people.append(tuple(points))
    return people


def mirror(person: Person) -> Person:
    """Left-right mirror: flip x and swap each left/right keypoint pair."""
    flipped = [None if p is None else (1.0 - p[0], p[1]) for p in person]
    for a, b in MIRROR_PAIRS:
        flipped[a], flipped[b] = flipped[b], flipped[a]
    return tuple(flipped)


def stick_width(width: int, height: int) -> int:
    """Width-4 limbs at 512 px in OpenPose: scale with the picture to stay legible."""
    return max(4, round(4 * min(width, height) / 512))


def render(people: Sequence[Person], width: int, height: int) -> Image.Image:
    """The OpenPose control image for ``people`` at ``width`` x ``height``."""
    import cv2

    if not (16 <= width <= MAX_RENDER_SIDE and 16 <= height <= MAX_RENDER_SIDE):
        raise PoseError(f"A pose picture must be 16 to {MAX_RENDER_SIDE} pixels a side.")
    canvas = np.zeros((height, width, 3), np.uint8)
    stick = stick_width(width, height)
    for person in people:
        for i, (a, b) in enumerate(LIMBS):
            pa, pb = person[a], person[b]
            if pa is None or pb is None:
                continue
            xs = (pa[0] * width, pb[0] * width)
            ys = (pa[1] * height, pb[1] * height)
            length = math.hypot(xs[0] - xs[1], ys[0] - ys[1])
            angle = math.degrees(math.atan2(ys[0] - ys[1], xs[0] - xs[1]))
            poly = cv2.ellipse2Poly(
                (round(sum(xs) / 2), round(sum(ys) / 2)),
                (round(length / 2), stick),
                round(angle),
                0,
                360,
                1,
            )
            cv2.fillConvexPoly(canvas, np.asarray(poly, np.int32), COLOURS[i])
    canvas = (canvas.astype(np.float32) * 0.6).astype(np.uint8)
    for person in people:
        for i, p in enumerate(person):
            if p is None:
                continue
            cv2.circle(
                canvas, (round(p[0] * width), round(p[1] * height)), stick, COLOURS[i], thickness=-1
            )
    return Image.fromarray(canvas)


def render_png(people: Sequence[Person], width: int, height: int) -> bytes:
    return png(render(people, width, height))


def people_json(people: Sequence[Person]) -> list[list[list[float] | None]]:
    return [
        [None if p is None else [round(p[0], 4), round(p[1], 4)] for p in person]
        for person in people
    ]


# ---------------------------------------------------------------------------------------------
# DWPose extraction (ONNX on the CPU)


def _session(path: Path) -> Any:
    import onnxruntime as ort  # type: ignore[import-untyped]  # no stubs shipped

    so = ort.SessionOptions()
    so.intra_op_num_threads = THREADS
    so.enable_cpu_mem_arena = False
    so.log_severity_level = 3
    try:
        return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
    except Exception:
        raise PoseError(
            f"The pose model file {path.name} is not usable. "
            "Reinstall it with `p11 models install control`."
        ) from None


def _nms(boxes: np.ndarray, scores: np.ndarray, threshold: float) -> list[int]:
    order = scores.argsort()[::-1]
    keep: list[int] = []
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    while order.size:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        ovr = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][ovr <= threshold]
    return keep


def _decode_yolox(out: np.ndarray, size: int) -> np.ndarray:
    grids, strides = [], []
    for stride in (8, 16, 32):
        n = size // stride
        xv, yv = np.meshgrid(np.arange(n), np.arange(n))
        grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((n * n, 1), stride))
    grid = np.concatenate(grids)
    stride_arr = np.concatenate(strides)
    pred = out.copy()
    pred[:, :2] = (pred[:, :2] + grid) * stride_arr
    pred[:, 2:4] = np.exp(pred[:, 2:4]) * stride_arr
    return pred


def _warp_matrix(center: np.ndarray, scale: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Box (centre, scale) → model input, no rotation (RTMPose ``get_warp_matrix``)."""
    import cv2

    w, h = size
    half = float(scale[0]) * 0.5
    cx, cy = float(center[0]), float(center[1])
    # Three points of one similarity: the centre, half a width up, half a width right.
    src = np.array([[cx, cy], [cx, cy - half], [cx + half, cy]], np.float32)
    dst = np.array([[w / 2, h / 2], [w / 2, h / 2 - w / 2], [w, h / 2]], np.float32)
    return np.asarray(cv2.getAffineTransform(src, dst))


@dataclass
class DwPose:
    detector_path: Path
    estimator_path: Path

    def __post_init__(self) -> None:
        self._det: Any = None
        self._pose: Any = None
        self._lock = threading.Lock()

    def _sessions(self) -> tuple[Any, Any]:
        with self._lock:
            if self._det is None:
                self._det = _session(self.detector_path)
                self._pose = _session(self.estimator_path)
            return self._det, self._pose

    def people_boxes(self, rgb: np.ndarray) -> np.ndarray:
        import cv2

        det, _ = self._sessions()
        size = 640
        h, w = rgb.shape[:2]
        r = min(size / h, size / w)
        padded = np.full((size, size, 3), 114, np.uint8)
        resized = cv2.resize(rgb, (int(w * r), int(h * r)), interpolation=cv2.INTER_LINEAR)
        padded[: resized.shape[0], : resized.shape[1]] = resized
        x = np.ascontiguousarray(padded.transpose(2, 0, 1)[None], dtype=np.float32)
        (out,) = det.run(None, {det.get_inputs()[0].name: x})
        pred = _decode_yolox(np.asarray(out)[0], size)
        scores = pred[:, 4] * pred[:, 5]  # objectness x person class
        keep_mask = scores > 0.1
        boxes = (
            np.stack(
                [
                    pred[:, 0] - pred[:, 2] / 2,
                    pred[:, 1] - pred[:, 3] / 2,
                    pred[:, 0] + pred[:, 2] / 2,
                    pred[:, 1] + pred[:, 3] / 2,
                ],
                1,
            )[keep_mask]
            / r
        )
        scores = scores[keep_mask]
        if not len(scores):
            return np.zeros((0, 4))
        keep = _nms(boxes, scores, 0.45)
        boxes, scores = boxes[keep], scores[keep]
        return np.asarray(boxes[scores > MIN_SCORE][:MAX_PEOPLE])

    def keypoints(self, rgb: np.ndarray, box: np.ndarray) -> Person:
        import cv2

        _, pose = self._sessions()
        h, w = rgb.shape[:2]
        in_w, in_h = 288, 384
        center: np.ndarray = np.array([(box[0] + box[2]) / 2, (box[1] + box[3]) / 2], np.float32)
        scale: np.ndarray = np.array([box[2] - box[0], box[3] - box[1]], np.float32) * 1.25
        aspect = in_w / in_h
        if scale[0] > scale[1] * aspect:
            scale = np.asarray([scale[0], scale[0] / aspect], dtype=np.float32)
        else:
            scale = np.asarray([scale[1] * aspect, scale[1]], dtype=np.float32)
        m = _warp_matrix(center, scale, (in_w, in_h))
        crop: np.ndarray = cv2.warpAffine(rgb, m, (in_w, in_h), flags=cv2.INTER_LINEAR).astype(
            np.float32
        )
        crop = (crop - np.array([123.675, 116.28, 103.53], np.float32)) / np.array(
            [58.395, 57.12, 57.375], np.float32
        )
        x = np.ascontiguousarray(crop.transpose(2, 0, 1)[None], dtype=np.float32)
        simcc_x, simcc_y = pose.run(None, {pose.get_inputs()[0].name: x})
        sx, sy = np.asarray(simcc_x)[0], np.asarray(simcc_y)[0]
        locs = np.stack([sx.argmax(1), sy.argmax(1)], 1).astype(np.float32) / 2.0
        vals = np.minimum(sx.max(1), sy.max(1))
        kps = locs / np.array([in_w, in_h], np.float32) * scale + center - scale / 2
        coco = [
            (float(kps[i, 0]) / w, float(kps[i, 1]) / h) if vals[i] > MIN_SCORE else None
            for i in range(17)
        ]
        out: list[Point] = []
        for idx in OPENPOSE_FROM_COCO:
            if idx >= 0:
                out.append(coco[idx])
            else:
                ls, rs = coco[5], coco[6]
                out.append(None if ls is None or rs is None else
                           ((ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2))  # fmt: skip
        return tuple(out)

    def extract(self, rgb: np.ndarray) -> list[Person]:
        people = [self.keypoints(rgb, b) for b in self.people_boxes(rgb)]
        return [p for p in people if sum(q is not None for q in p) >= 4]


class StubPose:
    """``p11 serve --fake`` and tests: one standing person, whatever the photo."""

    def extract(self, rgb: np.ndarray) -> list[Person]:
        return [STANDING]


#: A neutral standing pose (front view), also the editor's first stock pose.
STANDING: Person = (
    (0.5, 0.16), (0.5, 0.26),
    (0.4, 0.27), (0.37, 0.42), (0.36, 0.56),
    (0.6, 0.27), (0.63, 0.42), (0.64, 0.56),
    (0.44, 0.55), (0.44, 0.73), (0.44, 0.9),
    (0.56, 0.55), (0.56, 0.73), (0.56, 0.9),
    (0.48, 0.14), (0.52, 0.14), (0.46, 0.15), (0.54, 0.15),
)  # fmt: skip


def extract_people(image: bytes, estimator: Any) -> tuple[list[Person], tuple[int, int]]:
    try:
        img = open_rgb(image)
    except ImageError as exc:
        raise PoseError(str(exc)) from None
    people = estimator.extract(np.asarray(img))
    if not people:
        raise PoseError(NO_PERSON)
    return people, img.size


def pose_image_from_photo(image: bytes, estimator: Any) -> bytes:
    """Photo → OpenPose control image at the photo's size (capped), for ``Pose.preprocess``."""
    people, (w, h) = extract_people(image, estimator)
    s = min(1.0, 1024 / max(w, h))
    return render_png(people, max(16, round(w * s)), max(16, round(h * s)))

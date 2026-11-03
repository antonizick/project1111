"""Face detection, swap, restore and the S5 NSFW guard (Phase 12, ADR-0028/0029).

The real ONNX models run in ``tests/gpu/`` and in the acceptance run; here everything is the stub
kit, which is what ``p11 serve --fake`` and the FakeEngine tests use. The guard is exercised hard:
it refuses before a swap and again after it, and no call path can skip it.
"""

from __future__ import annotations

import io
import re

import numpy as np
import pytest
from PIL import Image

from p11.media import faces as F
from p11.media import nsfw as N

W, H = 200, 200


def img(colour: tuple[int, int, int] = (200, 120, 90), size: tuple[int, int] = (W, H)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    return buf.getvalue()


def unsafe_image() -> bytes:
    """A synthetic image the stub guard calls unsafe (magenta corners; not a real photo)."""
    im = Image.new("RGB", (W, H), (20, 20, 20))
    for x, y in ((0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)):
        im.putpixel((x, y), N.STUB_MARKER)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _code_only(text: str) -> str:
    """A file's code with docstrings and comments removed, so a scan sees only real code."""
    text = re.sub('""".*?"""', '""', text, flags=re.S)
    text = re.sub("'''.*?'''", "''", text, flags=re.S)
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


# ---------------------------------------------------------------------------------------------
# The guard


def test_stub_guard_marks_only_the_magenta_corners_unsafe() -> None:
    guard = N.StubGuard()
    assert not guard.verdict(Image.open(io.BytesIO(img()))).unsafe
    assert guard.verdict(Image.open(io.BytesIO(unsafe_image()))).unsafe


def test_guard_refuses_an_unsafe_target_before_anything_happens() -> None:
    guard = N.StubGuard()
    with pytest.raises(N.GuardRefused) as exc:
        N.check_target(guard, Image.open(io.BytesIO(unsafe_image())))
    assert "does not put faces onto nude or sexual images" in str(exc.value)


def test_guard_refuses_an_unsafe_result() -> None:
    guard = N.StubGuard()
    with pytest.raises(N.GuardRefused):
        N.check_result(guard, Image.open(io.BytesIO(unsafe_image())))


class _Classifier:
    def __init__(self, p: float) -> None:
        self.p = p

    def unsafe_probability(self, image: Image.Image) -> float:
        return self.p


def test_the_real_guard_needs_both_classifiers_and_fails_closed() -> None:
    both = {mid: _Classifier(0.0) for mid in N.GUARD_MODEL_IDS}
    assert not N.NsfwGuard(both).verdict(Image.new("RGB", (8, 8))).unsafe
    one = dict(both)
    one.pop(N.GUARD_MODEL_IDS[1])
    with pytest.raises(N.GuardUnavailable):
        N.NsfwGuard(one)


def test_either_classifier_refusing_is_enough() -> None:
    for which in (0, 1):
        classifiers = {mid: _Classifier(0.0) for mid in N.GUARD_MODEL_IDS}
        classifiers[N.GUARD_MODEL_IDS[which]] = _Classifier(0.9)
        assert N.NsfwGuard(classifiers).verdict(Image.new("RGB", (8, 8))).unsafe, which


def test_the_guard_thresholds_and_models_are_constants_not_settings() -> None:
    """S5: nothing in the settings, the routes or the schema can turn the guard off or tune it."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "p11"
    offenders: list[str] = []
    for path in src.rglob("*.py"):
        if path.name == "nsfw.py":
            continue
        for line in _code_only(path.read_text()).splitlines():
            low = line.lower()
            if "nsfw" in low and any(
                k in low for k in ("disable", "enable", "off", "setting", "env", "field")
            ):
                offenders.append(f"{path.name}: {line.strip()}")
    assert offenders == []
    config = _code_only((src / "config.py").read_text()).lower()
    assert "nsfw" not in config
    assert "guard" not in config


def test_no_recipe_field_can_weaken_the_guard() -> None:
    from p11.recipe.model import STEP_TYPES, FaceSwap

    assert "guard" not in FaceSwap.model_fields
    assert "nsfw" not in FaceSwap.model_fields
    assert set(STEP_TYPES) >= {"face_swap", "face_restore"}


# ---------------------------------------------------------------------------------------------
# Geometry


def test_iou_and_nms_keep_the_better_box() -> None:
    a = (0.0, 0.0, 10.0, 10.0)
    b = (1.0, 1.0, 11.0, 11.0)
    assert 0.6 < F.iou(a, b) < 0.7
    assert F.iou(a, (20.0, 20.0, 30.0, 30.0)) == 0.0
    faces = [
        F.Face(a, (), 0.9),
        F.Face(b, (), 0.8),
        F.Face((50.0, 50.0, 60.0, 60.0), (), 0.7),
    ]
    kept = F.merge_faces(faces)
    assert len(kept) == 2
    assert kept[0].box == a


def test_faces_are_ordered_largest_first() -> None:
    small = F.Face((0.0, 0.0, 10.0, 10.0), (), 0.99)
    big = F.Face((0.0, 0.0, 100.0, 100.0), (), 0.5)
    assert F.order_faces([small, big])[0] is big
    assert F.pick([small, big], 0, none="", what="target image") is big
    with pytest.raises(F.FaceError, match="face 3 does not exist"):
        F.pick([small], 2, none="", what="target image")
    with pytest.raises(F.FaceError, match="no face"):
        F.pick([], 0, none="P11 found no face in this image.", what="target image")


def test_similarity_transform_maps_points_exactly() -> None:
    src = np.array([[0.0, 0.0], [2.0, 0.0], [1.0, 1.0]])
    m = F.similarity_transform(src, src)
    assert np.allclose(m[:, :2], np.eye(2), atol=1e-9)
    assert np.allclose(m[:, 2], 0.0, atol=1e-9)
    # Rotate 90° and scale by 2 around the origin.
    dst = np.array([[0.0, 0.0], [0.0, 4.0], [-2.0, 2.0]])
    m = F.similarity_transform(src, dst)
    got = (np.hstack([src, np.ones((3, 1))]) @ m.T).round(6)
    assert np.allclose(got, dst, atol=1e-6)
    back = np.vstack([F.invert_affine(m), [0.0, 0.0, 1.0]])
    round_trip = np.hstack([dst, np.ones((3, 1))]) @ back.T
    assert np.allclose(round_trip[:, :2], src, atol=1e-6)


def test_box_mask_is_faded_in_the_middle_and_blacks_out_the_border() -> None:
    mask = F.box_mask(64)
    assert mask.shape == (64, 64)
    assert mask[32, 32] == pytest.approx(1.0)
    assert float(mask[0, 0]) < 0.05  # the blur leaks a little past the border
    assert 0.0 < mask[3, 32] < 1.0  # the feather band


def test_paste_back_only_touches_the_face_area() -> None:
    image = np.full((64, 64, 3), 100, np.uint8)
    crop = np.full((32, 32, 3), 255, np.float32)
    # image -> crop: the crop's (0, 0) came from the image's (16, 16).
    m = np.array([[1.0, 0.0, -16.0], [0.0, 1.0, -16.0]])
    out = F.paste_back(image, crop, np.ones((32, 32), np.float32), m)
    assert (out[:8, :8] == 100).all()
    assert out[24, 24, 0] == 255


# ---------------------------------------------------------------------------------------------
# The local steps


def kit() -> F.FaceKit:
    return F.FaceKit(stub=True)


def test_face_swap_happens_and_lands_on_the_detected_box() -> None:
    out = F.run_face_swap(
        {"restore": True, "restore_visibility": 0.5},
        {"image": img((20, 30, 200)), "face": img((220, 20, 20))},
        kit(),
    )
    made = Image.open(io.BytesIO(out["image"]))
    assert made.size == (W, H)
    assert made.getpixel((100, 76)) != (20, 30, 200)  # inside the stub's face box


def test_face_swap_refuses_an_unsafe_target() -> None:
    with pytest.raises(N.GuardRefused):
        F.run_face_swap({}, {"image": unsafe_image(), "face": img()}, kit())


def test_face_swap_refuses_when_the_result_looks_unsafe() -> None:
    class Guard(N.StubGuard):
        """Safe for the target, unsafe for the result: only the second check can catch this."""

        def __init__(self) -> None:
            self.calls = 0

        def verdict(self, image: Image.Image) -> N.Verdict:
            self.calls += 1
            return N.Verdict(self.calls > 1, (("stub", 1.0),))

    class Kit(F.FaceKit):
        def guard(self):  # type: ignore[override]
            return Guard()

    with pytest.raises(N.GuardRefused) as exc:
        F.run_face_swap({}, {"image": img(), "face": img()}, Kit(stub=True))
    assert "does not save face swaps" in str(exc.value)


def test_face_swap_needs_a_face_in_both_pictures() -> None:
    class NoFaces(F.FaceKit):
        def detector(self):  # type: ignore[override]
            class D:
                def detect(self, rgb):
                    return []

            return D()

    with pytest.raises(F.FaceError, match="no face in the face photo"):
        F.run_face_swap({}, {"image": img(), "face": img()}, NoFaces(stub=True))


def test_face_swap_picks_the_face_the_form_asked_for() -> None:
    class TwoFaces(F.FaceKit):
        def detector(self):  # type: ignore[override]
            base = kit().detector()

            class D:
                def detect(self, rgb):
                    f = base.detect(rgb)[0]
                    return [
                        F.Face(f.box, f.landmarks, f.score),
                        F.Face((1.0, 1.0, 20.0, 20.0), f.landmarks, f.score),
                    ]

            return D()

    out = F.run_face_swap(
        {"target_face_index": 1, "source_face_index": 0, "restore": False},
        {"image": img(), "face": img()},
        TwoFaces(stub=True),
    )
    assert out["image"][:8] == b"\x89PNG\r\n\x1a\n"


def test_face_restore_works_on_one_or_every_face() -> None:
    for index in (None, 0):
        out = F.run_face_restore({"face_index": index, "visibility": 1.0}, {"image": img()}, kit())
        assert out["image"][:8] == b"\x89PNG\r\n\x1a\n"


def test_face_restore_says_so_when_there_is_no_face() -> None:
    class NoFaces(F.FaceKit):
        def detector(self):  # type: ignore[override]
            class D:
                def detect(self, rgb):
                    return []

            return D()

    with pytest.raises(F.FaceError, match="no face to restore"):
        F.run_face_restore({}, {"image": img()}, NoFaces(stub=True))


def test_detect_faces_reports_boxes_for_the_ui() -> None:
    found, size = F.detect_faces(img(), kit())
    assert size == (W, H)
    assert len(found) == 1
    box = found[0].to_json(W, H)["box"]
    assert 0.0 < box[0] < box[2] <= 1.0


def test_the_face_model_ids_match_the_recipe_defaults() -> None:
    """The step compilers and the media modules must name the same manifest IDs."""
    from p11.recipe import presets

    assert F.DETECTOR_ID == presets.DEFAULT_DETECTOR
    assert F.RECOGNIZER_ID == presets.DEFAULT_RECOGNIZER
    assert F.SWAPPER_ID == presets.DEFAULT_SWAPPER
    assert F.RESTORER_ID == presets.DEFAULT_RESTORER
    assert N.GUARD_MODEL_IDS == presets.DEFAULT_GUARD_CLASSIFIERS


def test_every_face_model_licence_is_recorded_and_flagged() -> None:
    """R11/H3: the non-commercial InsightFace weights are flagged and need an acknowledgement."""
    from p11.models.manifest import load_manifest

    manifest = load_manifest()
    face_ids = {"yunet-2023mar", "arcface-w600k-r50", "inswapper-128", "gfpgan-1.4",
                "nsfw-marqo-384", "nsfw-freepik-eva02"}  # fmt: skip
    for entry in manifest:
        if entry.id not in face_ids:
            continue
        assert entry.licence.name and entry.licence.url
        if entry.id in ("arcface-w600k-r50", "inswapper-128"):
            assert entry.licence.commercial_use is False
            assert entry.licence.flags == ("non-commercial", "research-only")
            assert entry.licence.needs_acknowledgement
        assert "face" in entry.sets and "default" not in entry.sets
    assert {e.id for e in manifest if "face" in e.sets} == face_ids

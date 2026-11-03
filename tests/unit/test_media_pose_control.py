"""Pose and control-map preparation (Phase 12, ADR-0030): pure geometry and the CPU transforms."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from p11.media import control, pose

PERSON = [
    [0.5, 0.2], [0.5, 0.3], [0.4, 0.3], [0.35, 0.45], [0.34, 0.6],
    [0.6, 0.3], [0.65, 0.45], [0.66, 0.6], [0.45, 0.55], [0.45, 0.72],
    [0.45, 0.9], [0.55, 0.55], [0.55, 0.72], [0.55, 0.9], [0.48, 0.18],
    [0.52, 0.18], [0.46, 0.19], [0.54, 0.19],
]  # fmt: skip


def png(size: tuple[int, int] = (64, 64), colour=(120, 90, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------
# The pose model


def test_a_person_has_18_keypoints_and_round_trips() -> None:
    people = pose.parse_people([PERSON])
    assert len(people) == 1 and len(people[0]) == 18
    back = pose.people_json(people)
    assert back[0][0] == [0.5, 0.2]
    assert pose.parse_people(back) == people


def test_a_keypoint_can_be_missing() -> None:
    person = list(PERSON)
    person[4] = None
    people = pose.parse_people([person])
    assert people[0][4] is None


def test_malformed_poses_are_refused_in_plain_english() -> None:
    with pytest.raises(pose.PoseError, match="no people"):
        pose.parse_people([])
    with pytest.raises(pose.PoseError, match="18 keypoints"):
        pose.parse_people([[None] * 17])
    with pytest.raises(pose.PoseError, match=r"\[x, y\]"):
        pose.parse_people([[["a", 1]] * 18])
    with pytest.raises(pose.PoseError, match="far outside"):
        pose.parse_people([[[5.0, 5.0]] * 18])
    with pytest.raises(pose.PoseError, match="at most"):
        pose.parse_people([PERSON] * 9)


def test_mirror_swaps_left_and_right() -> None:
    person = pose.parse_people([PERSON])[0]
    m = pose.mirror(person)
    assert m[5] is not None and person[2] is not None
    assert m[5][0] == pytest.approx(1 - person[2][0])
    assert m[5][1] == pytest.approx(person[2][1])
    # The nose stays in the middle and the neck is untouched.
    assert m[0] == (1 - person[0][0], person[0][1])
    twice = pose.mirror(m)
    assert [tuple(round(c, 6) for c in pt) if pt else None for pt in twice] == list(person)


def test_render_draws_an_openpose_picture() -> None:
    people = pose.parse_people([PERSON])
    im = pose.render(people, 320, 480)
    assert im.size == (320, 480)
    assert im.convert("L").getextrema()[1] > 200  # coloured limbs on black
    data = pose.render_png(people, 64, 64)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_refuses_an_unusable_size() -> None:
    people = pose.parse_people([PERSON])
    with pytest.raises(pose.PoseError, match="16 to"):
        pose.render(people, 4, 4)
    with pytest.raises(pose.PoseError, match="16 to"):
        pose.render(people, 9000, 9000)


class _Stub:
    def extract(self, rgb: np.ndarray):
        return [pose.parse_people([PERSON])[0]]


class _None:
    def extract(self, rgb: np.ndarray):
        return []


def test_a_photo_becomes_a_skeleton_picture_at_the_right_size() -> None:
    out = pose.pose_image_from_photo(png((640, 480)), _Stub())
    im = Image.open(io.BytesIO(out))
    assert im.size == (640, 480)
    assert im.convert("L").getextrema()[1] > 0


def test_a_photo_without_a_person_says_so() -> None:
    with pytest.raises(pose.PoseError, match="no person"):
        pose.pose_image_from_photo(png(), _None())


def test_the_pose_model_ids_match_the_recipe_defaults() -> None:
    from p11.recipe import presets

    assert control.DEFAULT_POSE_DETECTOR == presets.DEFAULT_POSE_DETECTOR
    assert control.DEFAULT_POSE_ESTIMATOR == presets.DEFAULT_POSE_ESTIMATOR
    assert control.DEFAULT_DEPTH_MODEL == presets.DEFAULT_DEPTH_MODEL


# ---------------------------------------------------------------------------------------------
# Control maps


def test_canny_map_is_a_three_channel_edge_picture() -> None:
    im = Image.open(io.BytesIO(control.canny_map(png((80, 60), (255, 255, 255)))))
    assert im.size == (80, 60) and im.mode == "RGB"


def test_the_reference_photo_is_shrunk_for_the_clip_encoder() -> None:
    big = png((3000, 2000))
    out = Image.open(io.BytesIO(control.reference_image(big)))
    assert max(out.size) == control.REFERENCE_SIDE
    assert out.width / out.height == pytest.approx(1.5, abs=0.01)


class _Depth:
    def depth_map(self, image: Image.Image) -> bytes:
        return png(image.size, (10, 10, 10))


def test_the_stub_controls_do_the_same_shapes_as_the_real_ones() -> None:
    kit = control.Controls(stub=True)
    for kind in ("pose", "depth", "canny", "reference"):
        out = kit.transform(kind, png((320, 240)))
        assert out[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(control.ControlError, match="does not know"):
        kit.transform("magic", png())


def test_a_missing_control_model_says_what_to_install() -> None:
    kit = control.Controls(resolve=lambda mid: Path("/nope") / mid)
    with pytest.raises(control.ControlError, match="p11 models install control"):
        kit.transform("depth", png())

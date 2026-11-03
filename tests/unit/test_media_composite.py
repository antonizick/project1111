"""Compositing for background replacement: geometry, colour transfer, blending (Phase 11).

Pure parts get exact assertions; the pipeline gets pixel-level checks with known masks. Colour
matching is off where the test checks pixel identity, so the assertions do not depend on the
tuning.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from p11.media.composite import (
    CompositeError,
    CompositeParams,
    colour_transfer,
    compose,
    edge_band,
    fit_box,
    lab_stats,
    lab_to_srgb,
    parse_colour,
    place_box,
    run_replace_background,
    srgb_to_lab,
    unmix_spill,
)
from p11.media.segment import Segmenters


def rgb(size: tuple[int, int], colour: tuple[int, int, int]) -> bytes:
    return _png(Image.new("RGB", size, colour))


def mask(size: tuple[int, int], boxes: list[tuple[int, int, int, int]]) -> bytes:
    m = Image.new("L", size, 0)
    for box in boxes:
        for x in range(box[0], box[2]):
            for y in range(box[1], box[3]):
                m.putpixel((x, y), 255)
    return _png(m)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def pixels(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


# -- geometry ---------------------------------------------------------------------------------


def test_fit_box_covers_the_canvas():
    assert fit_box((100, 50), (200, 200), "cover", 0.5, 0.5) == (-100, 0, 300, 200)
    assert fit_box((100, 50), (200, 200), "cover", 0.0, 0.5) == (0, 0, 400, 200)
    assert fit_box((100, 50), (200, 200), "cover", 1.0, 0.5) == (-200, 0, 200, 200)


def test_fit_box_contains_inside_the_canvas():
    assert fit_box((100, 50), (200, 200), "contain", 0.5, 0.5) == (0, 50, 200, 150)
    assert fit_box((100, 50), (200, 200), "contain", 0.5, 0.0) == (0, 0, 200, 100)


def test_place_box_scale_and_anchor():
    assert place_box((100, 100), (50, 50), 1.0, 0.5, 0.5) == (25, 25, 75, 75)
    assert place_box((100, 100), (50, 50), 2.0, 0.5, 0.5) == (0, 0, 100, 100)
    assert place_box((100, 100), (50, 50), 1.0, 0.0, 1.0) == (0, 50, 50, 100)


def test_geometry_rejects_empty_images():
    with pytest.raises(ValueError):
        fit_box((0, 5), (10, 10), "cover", 0.5, 0.5)
    with pytest.raises(ValueError):
        place_box((10, 10), (5, 5), 0.0, 0.5, 0.5)


# -- colour -----------------------------------------------------------------------------------


def test_lab_round_trip():
    rng = np.random.default_rng(7)
    rgb_arr = rng.uniform(0, 255, (9, 4, 3))
    back = lab_to_srgb(srgb_to_lab(rgb_arr))
    assert np.abs(back - rgb_arr).max() < 1.0


def test_lab_stats_weights():
    pixels_arr = np.zeros((2, 3))
    pixels_arr[1] = (10.0, 20.0, 30.0)
    mean, sigma = lab_stats(pixels_arr, np.array([1.0, 0.0]))
    assert mean == pytest.approx((0.0, 0.0, 0.0))
    assert sigma == pytest.approx((0.0, 0.0, 0.0))


def test_colour_transfer_zero_strength_is_identity():
    subj = np.full((4, 4, 3), (200, 100, 50), np.float32)
    alpha = np.ones((4, 4), np.float32)
    ref = np.full((4, 4, 3), (10, 20, 30), np.float32)
    out = colour_transfer(subj, alpha, ref, 0.0)
    assert np.abs(out - subj).max() < 0.5


def test_colour_transfer_moves_the_subject_toward_the_background():
    subj = np.full((4, 4, 3), (200, 200, 200), np.float32)
    alpha = np.ones((4, 4), np.float32)
    ref = np.full((4, 4, 3), (200, 30, 30), np.float32)  # warm background
    out = colour_transfer(subj, alpha, ref, 1.0)
    # The subject starts neutral; after the transfer its red-blue balance matches the background.
    assert out[..., 0].mean() > out[..., 2].mean() + 50


def test_unmix_spill_only_touches_the_blend_band():
    subj = np.full((3, 3, 3), 100.0, np.float32)
    bg = np.full((3, 3, 3), 200.0, np.float32)
    alpha = np.full((3, 3), 1.0, np.float32)
    out = unmix_spill(subj, bg, alpha)  # fully opaque: untouched
    assert np.array_equal(out, subj)
    soft = np.full((3, 3), 0.5, np.float32)
    mixed = 0.5 * subj + 0.5 * bg  # what the camera would see
    unmixed = unmix_spill(mixed, bg, soft)
    assert np.abs(unmixed - subj).max() < 1.0


# -- masks ------------------------------------------------------------------------------------


def test_edge_band_is_a_ring_around_the_edge():
    m = Image.open(io.BytesIO(mask((128, 128), [(32, 32, 96, 96)])))
    out = np.asarray(edge_band(m), np.float32)
    assert out[32, 64] > 40  # on the edge
    assert out[64, 64] < 30  # deep inside the subject
    assert out[4, 4] < 30  # far outside


# -- compose ----------------------------------------------------------------------------------


def test_compose_photo_background_pixel_identity():
    subject = rgb((8, 8), (255, 255, 255))
    background = rgb((8, 8), (0, 0, 255))
    m = mask((8, 8), [(0, 0, 8, 4)])  # top half is subject
    params = CompositeParams(colour_match=False, feather_px=0)
    out, alpha = compose(subject, background, m, params)
    img = pixels(_png(out))
    assert img.getpixel((4, 1)) == (255, 255, 255)  # subject
    assert img.getpixel((4, 6)) == (0, 0, 255)  # background
    assert alpha.getpixel((4, 1)) == 255 and alpha.getpixel((4, 6)) == 0
    assert out.mode == "RGB"


def test_compose_flat_colour_and_transparent():
    subject = rgb((4, 4), (10, 10, 10))
    m = mask((4, 4), [(0, 0, 2, 4)])
    flat, _ = compose(
        subject,
        None,
        m,
        CompositeParams(colour_match=False, feather_px=0, background_colour="#ff0000"),
    )
    assert flat.mode == "RGB"
    assert flat.getpixel((3, 0)) == (255, 0, 0)
    clear, _ = compose(
        subject, None, m, CompositeParams(feather_px=0, background_colour="#00000000")
    )
    assert clear.mode == "RGBA"
    assert clear.getpixel((3, 0))[3] == 0 and clear.getpixel((0, 0))[3] == 255


def test_compose_needs_a_background_and_a_mask():
    subject = rgb((4, 4), (1, 2, 3))
    m = mask((4, 4), [(0, 0, 2, 2)])
    with pytest.raises(CompositeError):
        compose(subject, None, m, CompositeParams())
    with pytest.raises(CompositeError):
        compose(subject, rgb((4, 4), (9, 9, 9)), mask((4, 4), []), CompositeParams())


def test_compose_subject_placement():
    subject = rgb((8, 8), (255, 255, 255))
    background = rgb((8, 8), (0, 0, 0))
    m = mask((8, 8), [(0, 0, 8, 8)])
    params = CompositeParams(
        colour_match=False, feather_px=0, subject_scale=0.5, subject_x=0.0, subject_y=0.0
    )
    out, _ = compose(subject, background, m, params)
    img = pixels(_png(out))
    assert img.getpixel((1, 1)) == (255, 255, 255)  # subject at half size, top-left
    assert img.getpixel((7, 7)) == (0, 0, 0)  # rest is background


# -- the step pipeline -------------------------------------------------------------------------


def test_run_replace_background_segments_and_composites():
    subject = rgb((16, 16), (250, 250, 250))
    background = rgb((16, 16), (0, 0, 250))
    out = run_replace_background(
        {"colour_match": False, "feather_px": 0},
        {"image": subject, "background": background},
        Segmenters(stub=True),
    )
    img = pixels(out["image"])
    band = Image.open(io.BytesIO(out["mask"]))
    assert band.size == (16, 16)
    # The stub keeps an ellipse of the subject; the corner is background.
    assert img.getpixel((15, 15)) == (0, 0, 250)
    assert img.getpixel((8, 8)) == (250, 250, 250)


def test_run_replace_background_prefers_the_given_mask():
    subject = rgb((8, 8), (255, 255, 255))
    background = rgb((8, 8), (0, 0, 0))
    m = mask((8, 8), [(0, 0, 8, 2)])
    out = run_replace_background(
        {"colour_match": False, "feather_px": 0},
        {"image": subject, "background": background, "mask": m},
        Segmenters(stub=True),
    )
    img = pixels(out["image"])
    assert img.getpixel((4, 1)) == (255, 255, 255)
    assert img.getpixel((4, 7)) == (0, 0, 0)


def test_parse_colour():
    assert parse_colour("#ff0080") == (255, 0, 128, 255)
    assert parse_colour("#ff008080") == (255, 0, 128, 128)
    assert parse_colour(None) is None
    with pytest.raises(CompositeError):
        parse_colour("red")

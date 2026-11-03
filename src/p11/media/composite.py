"""Background compositing for the ``replace_background`` step (Phase 11, ADR-0027).

The step's work that is not engine work happens here, on the CPU, in one place: segment the
subject (``p11.media.segment``), fit the background photo, move/scale the subject, match colours,
clean the edge, add an optional drop shadow and blend with a feathered mask. When the step also
harmonizes (``relight``), the engine's low-denoise inpaint pass runs over the ``edge_band`` this
module returns — the seam on both sides — and everything outside it is left untouched
(``p11.media.inpaint`` crop-and-stitch).

Colour matching transfers LAB mean/standard deviation from the background to the subject at a
chosen strength (0 = keep the subject's colours). Edge decontamination "unmixes" background spill
from the pixels in the feather band before the blend, which is what keeps a cut-out from showing a
halo of the old background.

Everything in the geometry and colour sections is pure (numpy/Pillow only, no I/O) and unit-tested;
the pipeline functions take and return PNG bytes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

import numpy as np
from PIL import Image, ImageChops, ImageFilter

from p11.media.imageio import open_mask, open_rgb, png
from p11.media.inpaint import grow
from p11.media.segment import Segments

Box = tuple[int, int, int, int]

#: Harmonize ring: half-width of the seam band as a fraction of the shorter side (tuned in
#: ``docs/P11_BENCHMARKS.md`` → Background replacement).
BAND_FRACTION = 0.025
BAND_MIN_PX = 12

EMPTY = "The mask is empty. Paint over the subject you want to keep."
NO_SUBJECT = "P11 could not find a subject in this image. Press Refine and paint the mask by hand."
NEEDS_BACKGROUND = "This step needs a background photo or a background colour."


class CompositeError(ValueError):
    """The composite cannot be made; the message says what to do."""


# ---------------------------------------------------------------------------------------------
# Pure geometry


def fit_box(
    bg: tuple[int, int],
    canvas: tuple[int, int],
    fit: Literal["cover", "contain"],
    x: float,
    y: float,
) -> Box:
    """Where a background of ``bg`` is drawn on ``canvas`` (may extend past the edges).

    ``cover`` fills the canvas (cropping overhang), ``contain`` fits inside it; ``x``/``y`` (0..1)
    place the scaled image between the two extremes.
    """
    bw, bh = bg
    cw, ch = canvas
    if bw <= 0 or bh <= 0 or cw <= 0 or ch <= 0:
        raise ValueError("images must not be empty")
    s = max(cw / bw, ch / bh) if fit == "cover" else min(cw / bw, ch / bh)
    sw, sh = max(1, round(bw * s)), max(1, round(bh * s))
    left, top = round((cw - sw) * x), round((ch - sh) * y)
    return (left, top, left + sw, top + sh)


def place_box(
    canvas: tuple[int, int], subj: tuple[int, int], scale: float, x: float, y: float
) -> Box:
    """Where the subject is drawn: its natural size times ``scale``, anchored by ``x``/``y``."""
    if scale <= 0:
        raise ValueError("scale must be positive")
    cw, ch = canvas
    sw, sh = max(1, round(subj[0] * scale)), max(1, round(subj[1] * scale))
    left, top = round((cw - sw) * x), round((ch - sh) * y)
    return (left, top, left + sw, top + sh)


# ---------------------------------------------------------------------------------------------
# Pure colour (sRGB <-> CIELAB, D65)


_M = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]
)
_M_INV = np.linalg.inv(_M)
_WHITE = np.array([0.95047, 1.0, 1.08883])
#: Lab standard deviations below this are noise; stops a flat subject from being blown up.
MIN_SIGMA = 4.0
#: How much of the background's chroma (a/b: tint) statistics apply to the subject: mean and
#: spread both. Lightness (L) transfers in full; limiting the tint keeps a saturated subject (a red
#: mug) from being dragged to the background's dominant hue (tuned on the 10-pair set, see
#: ``docs/P11_BENCHMARKS.md`` -> Background replacement).
CHROMA_SIGMA = 0.35


def srgb_to_lab(arr: np.ndarray) -> np.ndarray:
    """``arr`` (…, 3) float sRGB 0..255 → CIELAB."""
    c = np.clip(arr, 0.0, 255.0) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = (lin @ _M.T) / _WHITE
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    return np.stack(
        [
            116.0 * f[..., 1] - 16.0,
            500.0 * (f[..., 0] - f[..., 1]),
            200.0 * (f[..., 1] - f[..., 2]),
        ],
        axis=-1,
    )


def lab_to_srgb(lab: np.ndarray) -> np.ndarray:
    """CIELAB → sRGB 0..255 (clipped)."""
    fy = (lab[..., 0] + 16.0) / 116.0
    fx = fy + lab[..., 1] / 500.0
    fz = fy - lab[..., 2] / 200.0

    def finv(f: np.ndarray) -> np.ndarray:
        return np.where(f**3 > 0.008856, f**3, (f - 16.0 / 116.0) / 7.787)

    xyz = np.stack([finv(fx), finv(fy), finv(fz)], axis=-1) * _WHITE
    lin = xyz @ _M_INV.T
    c = np.where(
        lin <= 0.0031308, 12.92 * lin, 1.055 * np.power(np.clip(lin, 0.0, None), 1.0 / 2.4) - 0.055
    )
    return cast("np.ndarray", np.clip(c * 255.0, 0.0, 255.0))


def lab_stats(
    pixels: np.ndarray, weights: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Per-channel weighted mean and standard deviation of ``pixels`` (…, 3) in LAB."""
    flat = pixels.reshape(-1, 3).astype(np.float64)
    if weights is None:
        mean = flat.mean(axis=0)
        sigma = flat.std(axis=0)
    else:
        w = np.asarray(weights, np.float64).reshape(-1)
        total = float(w.sum())
        if total <= 0:
            return lab_stats(pixels)
        mean = (flat * w[:, None]).sum(axis=0) / total
        var = ((flat - mean) ** 2 * w[:, None]).sum(axis=0) / total
        sigma = np.sqrt(var)
    return mean, sigma


def colour_transfer(
    subject: np.ndarray,
    alpha: np.ndarray,
    reference: np.ndarray,
    strength: float,
) -> np.ndarray:
    """LAB mean/std transfer from ``reference`` to ``subject``, faded by ``strength``xalpha.

    ``subject`` and ``reference`` are sRGB 0..255 arrays (…, 3); ``alpha`` is 0..1 over the subject.
    """
    if strength <= 0:
        return subject
    src = srgb_to_lab(subject)
    dst = srgb_to_lab(reference)
    mu_s, sd_s = lab_stats(src, alpha)
    mu_d, sd_d = lab_stats(dst)
    sd_s = np.maximum(sd_s, MIN_SIGMA)
    k = np.array([1.0, CHROMA_SIGMA, CHROMA_SIGMA])
    transferred = (src - mu_s) * (1.0 + k * (sd_d / sd_s - 1.0)) + mu_s + k * (mu_d - mu_s)
    fade = np.clip(strength, 0.0, 1.0) * np.clip(alpha, 0.0, 1.0)[..., None]
    return lab_to_srgb(src + fade * (transferred - src))


def spill_background(original: np.ndarray, alpha: np.ndarray, radius: int) -> np.ndarray:
    """What the subject was photographed against, estimated just outside the mask.

    The pixels in the feather band are a mix of subject and the **old** background; to unmix them
    P11 needs that background's colour locally. Confident background pixels (soft alpha ~ 0) are
    blurred with a normalized blur, so each edge pixel gets the nearby outside colours.
    """
    outside = (np.clip(alpha, 0.0, 1.0) < 0.02).astype(np.float32)
    blurred_weight = np.asarray(
        Image.fromarray((outside * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius)),
        np.float32,
    ) / 255.0
    filled = original * outside[..., None]
    blurred_colours = np.asarray(
        Image.fromarray(np.clip(filled, 0, 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(radius)
        ),
        np.float32,
    )
    return blurred_colours / np.maximum(blurred_weight, 1e-4)[..., None]


def unmix_spill(subject: np.ndarray, old_bg: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Remove old-background spill from pixels partly covered by the mask (edge decontamination)."""
    a = np.clip(alpha, 0.0, 1.0)[..., None]
    band = (a > 0.1) & (a < 0.95)
    unmixed = (subject - (1.0 - a) * old_bg) / np.maximum(a, 0.05)
    return np.where(band, np.clip(unmixed, 0.0, 255.0), subject)


# ---------------------------------------------------------------------------------------------
# Masks


def feather(mask: Image.Image, px: int) -> Image.Image:
    return mask.filter(ImageFilter.GaussianBlur(px)) if px > 0 else mask


def edge_band(alpha: Image.Image, width_frac: float = BAND_FRACTION) -> Image.Image:
    """The seam ring: a band about ``width_frac`` of the short side wide, centred on the edge."""
    width = max(BAND_MIN_PX, round(width_frac * min(alpha.size)))
    outside = grow(alpha, width)
    inside = ImageChops.invert(grow(ImageChops.invert(alpha), width))
    band = ImageChops.subtract(outside, inside)
    return band.filter(ImageFilter.GaussianBlur(max(2, width // 2)))


def shadow_alpha(alpha: Image.Image) -> Image.Image:
    """A soft drop shadow of ``alpha``, offset down-right by ~2 %/3 % of the canvas."""
    w, h = alpha.size
    dx, dy = round(w * 0.02), round(h * 0.03)
    blur = max(2, round(w * 0.02))
    out = Image.new("L", alpha.size, 0)
    out.paste(alpha.filter(ImageFilter.GaussianBlur(blur)), (dx, dy))
    return out


# ---------------------------------------------------------------------------------------------
# Pipeline


@dataclass(frozen=True)
class CompositeParams:
    colour_match: bool = True
    colour_match_strength: float = 1.0
    feather_px: int = 8
    fit: Literal["cover", "contain"] = "cover"
    background_x: float = 0.5
    background_y: float = 0.5
    subject_scale: float = 1.0
    subject_x: float = 0.5
    subject_y: float = 0.5
    shadow: bool = False
    #: Flat background: "#rrggbb" or "#rrggbbaa" (alpha 0 = transparent PNG output).
    background_colour: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> CompositeParams:
        names = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in names})


def parse_colour(value: str | None) -> tuple[int, int, int, int] | None:
    """``#rrggbb`` or ``#rrggbbaa`` → RGBA, or ``None`` for no flat colour."""
    if value is None:
        return None
    v = value.removeprefix("#")
    if len(v) == 6:
        v += "ff"
    if len(v) != 8:
        raise CompositeError(f"{value!r} is not a colour like #1a2b3c.")
    try:
        return tuple(int(v[i : i + 2], 16) for i in (0, 2, 4, 6))  # type: ignore[return-value]
    except ValueError:
        raise CompositeError(f"{value!r} is not a colour like #1a2b3c.") from None


def _background_layer(
    canvas: tuple[int, int], background: bytes | None, params: CompositeParams
) -> tuple[np.ndarray, np.ndarray]:
    """The background as sRGB floats (h, w, 3) and its alpha (h, w) 0..1."""
    cw, ch = canvas
    colour = parse_colour(params.background_colour)
    if colour is not None:
        r, g, b, a = colour
        rgb = np.empty((ch, cw, 3), np.float32)
        rgb[..., 0], rgb[..., 1], rgb[..., 2] = r, g, b
        al = np.full((ch, cw), a / 255.0, np.float32)
        return rgb, al
    if background is None:
        raise CompositeError(NEEDS_BACKGROUND)
    bg = open_rgb(background)
    canvas_img = Image.new("RGB", canvas, (0, 0, 0))
    if params.fit == "contain":
        cover = fit_box(bg.size, canvas, "cover", params.background_x, params.background_y)
        csize = (cover[2] - cover[0], cover[3] - cover[1])
        canvas_img.paste(bg.resize(csize, Image.Resampling.LANCZOS), cover[:2])
    box = fit_box(bg.size, canvas, params.fit, params.background_x, params.background_y)
    canvas_img.paste(
        bg.resize((box[2] - box[0], box[3] - box[1]), Image.Resampling.LANCZOS), box[:2]
    )
    return np.asarray(canvas_img, np.float32), np.ones((ch, cw), np.float32)


def compose(
    subject: bytes,
    background: bytes | None,
    mask: bytes,
    params: CompositeParams,
) -> tuple[Image.Image, Image.Image]:
    """The composited image and the soft subject alpha used to make it.

    The result keeps the subject image's size. It is RGB for a photo background and RGBA for a
    flat colour (with alpha) or a transparent background.
    """
    subj = open_rgb(subject)
    canvas = subj.size
    alpha0 = open_mask(mask)
    if alpha0.size != canvas:
        alpha0 = alpha0.resize(canvas, Image.Resampling.BILINEAR)
    if alpha0.getbbox() is None:
        raise CompositeError(EMPTY)

    bg_rgb, bg_a = _background_layer(canvas, background, params)

    box = place_box(canvas, subj.size, params.subject_scale, params.subject_x, params.subject_y)
    subj_c = Image.new("RGB", canvas, (0, 0, 0))
    subj_c.paste(subj.resize((box[2] - box[0], box[3] - box[1]), Image.Resampling.LANCZOS), box[:2])
    alpha_c = Image.new("L", canvas, 0)
    bsize = (box[2] - box[0], box[3] - box[1])
    alpha_c.paste(alpha0.resize(bsize, Image.Resampling.BILINEAR), box[:2])

    soft = np.asarray(feather(alpha_c, params.feather_px), np.float32) / 255.0
    s_rgb = np.asarray(subj_c, np.float32)

    if params.colour_match:
        s_rgb = colour_transfer(s_rgb, soft, bg_rgb, params.colour_match_strength)
    if (soft < 0.02).any():
        old_bg = spill_background(s_rgb, soft, max(8, 2 * params.feather_px))
        s_rgb = unmix_spill(s_rgb, old_bg, soft)

    shadow = None
    if params.shadow:
        shadow = np.asarray(shadow_alpha(alpha_c), np.float32) / 255.0
        bg_rgb = bg_rgb * (1.0 - 0.35 * shadow[..., None])
        bg_a = bg_a * (1.0 - 0.35 * shadow)

    a = soft[..., None]
    out_a = soft + (1.0 - soft) * bg_a
    out_rgb = a * s_rgb + (1.0 - a) * (bg_a[..., None] * bg_rgb)
    with np.errstate(invalid="ignore", divide="ignore"):
        out_rgb = np.where(out_a[..., None] > 0, out_rgb / np.maximum(out_a[..., None], 1e-6), 0.0)

    alpha_img = Image.fromarray((soft * 255.0).astype(np.uint8))
    opaque = bool(np.all(bg_a >= 1.0))
    if opaque:
        result = Image.fromarray(np.clip(out_rgb, 0, 255).astype(np.uint8))
    else:
        rgba = np.concatenate([np.clip(out_rgb, 0, 255), out_a[..., None] * 255.0], axis=-1)
        result = Image.fromarray(rgba.astype(np.uint8))
    return result, alpha_img


def run_replace_background(
    params: Mapping[str, Any], inputs: Mapping[str, bytes], segments: Segments
) -> dict[str, bytes]:
    """The ``replace_background`` local step: segment (unless a mask is given), composite, band.

    Inputs: ``image`` (the subject), optional ``background`` photo, optional ``mask``. Returns
    ``image`` (the composite) and ``mask`` (the harmonize seam band for the engine pass).
    """
    subject = inputs["image"]
    mask = inputs.get("mask")
    auto = mask is None
    p = CompositeParams.from_mapping(params)
    if mask is None:
        mask = segments.segmenter(params.get("segmentation_model")).mask(subject)
    try:
        result, alpha = compose(subject, inputs.get("background"), mask, p)
    except CompositeError as exc:
        if auto and str(exc) == EMPTY:
            raise CompositeError(NO_SUBJECT) from None
        raise
    return {"image": png(result), "mask": png(edge_band(alpha))}

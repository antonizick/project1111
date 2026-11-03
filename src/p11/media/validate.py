"""Upload validation by content (spec S8): images through Pillow, videos through ffprobe.

Nothing here trusts a file name, extension or declared MIME type. Images are fully decoded,
size-capped, turned upright and re-encoded as PNG without EXIF (so GPS never reaches disk).
Videos are probed, checked against a container/codec allowlist and the R13 limits, and remuxed
without metadata (``-map_metadata -1``; MP4 ``location`` tags go too) and without re-encoding.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image, ImageOps

ImageKind = Literal["image", "mask"]

IMAGE_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})
#: 40 MP: above an 8K-wide photo; anything bigger is refused before decoding.
MAX_PIXELS = 40_000_000
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_SIDE = 12_000

#: ffprobe ``format_name`` values (comma lists as ffprobe prints them).
VIDEO_CONTAINERS = {"mov,mp4,m4a,3gp,3g2,mj2": "mp4", "matroska,webm": "matroska"}
VIDEO_CODECS = frozenset({"h264", "hevc", "vp8", "vp9", "av1", "mpeg4"})
AUDIO_CODECS = frozenset(
    {"aac", "mp3", "opus", "vorbis", "flac", "alac", "ac3", "eac3", "pcm_s16le", "pcm_s24le"}
)
MAX_VIDEO_BYTES = 1024 * 1024 * 1024
#: Hard caps; the R13 defaults (60 s, 1080p) only warn (they are settings).
HARD_MAX_SECONDS = 600.0
HARD_MAX_HEIGHT = 2160
PROBE_TIMEOUT = 30.0
REMUX_TIMEOUT = 300.0


class UploadRejected(ValueError):
    """The upload is not acceptable; the message is plain English and says why."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True)
class ValidImage:
    png: bytes
    width: int
    height: int
    source_format: str
    sha256: str


@dataclass(frozen=True)
class VideoInfo:
    container: str
    codec: str
    audio_codec: str | None
    width: int
    height: int
    seconds: float
    fps: float
    warnings: tuple[str, ...] = field(default=())


def validate_image(data: bytes, kind: ImageKind = "image") -> ValidImage:
    if len(data) > MAX_IMAGE_BYTES:
        raise UploadRejected(
            f"The image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
            "Use a smaller or more compressed image.",
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            opened = Image.open(io.BytesIO(data))
            img: Image.Image = opened
            fmt = (opened.format or "").upper()
            if fmt not in IMAGE_FORMATS:
                raise UploadRejected(
                    "This file is not a PNG, JPEG or WebP image.",
                    "Export it as PNG or JPEG and try again.",
                )
            w, h = img.size
            if w * h > MAX_PIXELS or max(w, h) > MAX_SIDE:
                raise UploadRejected(
                    f"The image is too large ({w}x{h}).",
                    f"Resize it below {MAX_PIXELS // 1_000_000} megapixels.",
                )
            img.load()
            img = ImageOps.exif_transpose(img)
    except UploadRejected:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Warning) as exc:
        raise UploadRejected(
            "This file is not a readable image.", "Check that it opens in an image viewer."
        ) from exc
    if kind == "mask":
        img = img.convert("L")
    elif img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() or "transparency" in img.info else "RGB")
    out = io.BytesIO()
    # No ``exif=``/``pnginfo=``: Pillow writes neither, so EXIF (incl. GPS) and text are dropped.
    img.save(out, format="PNG", optimize=False)
    png = out.getvalue()
    return ValidImage(png, img.width, img.height, fmt, hashlib.sha256(png).hexdigest())


# ---------------------------------------------------------------------------------------------
# Video


def _ffbin(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise UploadRejected(
            f"{name} is not installed, so P11 cannot check videos.",
            "Install ffmpeg (`sudo pacman -S ffmpeg`).",
        )
    return found


def _rate(text: str) -> float:
    num, _, den = text.partition("/")
    try:
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe_video(path: Path) -> dict[str, object]:
    try:
        r = subprocess.run(
            [
                _ffbin("ffprobe"),
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            timeout=PROBE_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise UploadRejected("Checking the video took too long.") from exc
    if r.returncode != 0:
        raise UploadRejected(
            "This file is not a readable video.", "Use an MP4, MOV, MKV or WebM file."
        )
    data = json.loads(r.stdout or b"{}")
    if not isinstance(data, dict):
        raise UploadRejected("This file is not a readable video.")
    return data


def check_video(
    probe: dict[str, object], *, warn_seconds: float = 60.0, warn_height: int = 1080
) -> VideoInfo:
    fmt = probe.get("format")
    streams = probe.get("streams")
    if not isinstance(fmt, dict) or not isinstance(streams, list):
        raise UploadRejected("This file is not a readable video.")
    container = str(fmt.get("format_name", ""))
    if container not in VIDEO_CONTAINERS:
        raise UploadRejected(
            "This video container is not supported.", "Use an MP4, MOV, MKV or WebM file."
        )
    video = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"]
    video = [s for s in video if not (s.get("disposition") or {}).get("attached_pic")]
    audio = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"]
    if not video:
        raise UploadRejected("The file has no video track.")
    v = video[0]
    codec = str(v.get("codec_name", ""))
    if codec not in VIDEO_CODECS:
        raise UploadRejected(
            f"The video codec {codec or 'unknown'} is not supported.",
            "Re-encode it as H.264 or VP9.",
        )
    audio_codec = str(audio[0].get("codec_name", "")) if audio else None
    if audio_codec is not None and audio_codec not in AUDIO_CODECS:
        raise UploadRejected(
            f"The audio codec {audio_codec} is not supported.", "Re-encode the audio as AAC."
        )
    try:
        width, height = int(v.get("width", 0)), int(v.get("height", 0))
        seconds = float(fmt.get("duration") or v.get("duration") or 0)
    except (TypeError, ValueError) as exc:
        raise UploadRejected("The video's size or length cannot be read.") from exc
    if width <= 0 or height <= 0 or seconds <= 0:
        raise UploadRejected("The video's size or length cannot be read.")
    short = min(width, height)
    if seconds > HARD_MAX_SECONDS:
        raise UploadRejected(
            f"The video is {seconds:.0f} s long; P11 takes at most {HARD_MAX_SECONDS:.0f} s.",
            "Trim it first.",
        )
    if short > HARD_MAX_HEIGHT:
        raise UploadRejected(
            f"The video is {width}x{height}; P11 takes at most {HARD_MAX_HEIGHT}p.",
            "Scale it down first.",
        )
    notes = []
    if seconds > warn_seconds:
        notes.append(f"Longer than {warn_seconds:.0f} s: face-swapping it will take a long time.")
    if short > warn_height:
        notes.append(f"Above {warn_height}p: it will be slow; 1080p is recommended.")
    fps = _rate(str(v.get("avg_frame_rate") or v.get("r_frame_rate") or "0"))
    return VideoInfo(
        VIDEO_CONTAINERS[container], codec, audio_codec, width, height, seconds, fps, tuple(notes)
    )


def strip_video_metadata(src: Path, dest: Path, container: str) -> None:
    """Remux the first video and audio track into ``dest`` without any metadata or chapters."""
    try:
        r = subprocess.run(
            [
                _ffbin("ffmpeg"),
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-i",
                str(src),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
                "-c",
                "copy",
                "-f",
                container,
                str(dest),
            ],
            capture_output=True,
            timeout=REMUX_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise UploadRejected("Storing the video took too long.") from exc
    if r.returncode != 0:
        raise UploadRejected("The video could not be stored (remux failed).")

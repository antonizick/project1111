"""System ffmpeg/ffprobe wrappers for the video face-swap pipeline (Phase 13, R13, spec S8).

Everything here builds **argument lists** and runs them with ``subprocess`` (never a shell string,
S8): the binary comes from ``shutil.which`` and every path is one argument. The same binary pair
validates uploads (``p11.media.validate``); the version in use is recorded by ``ffmpeg_version()``
and in the benchmarks.

Parsing is pure (``parse_probe`` on the ffprobe JSON) so VFR, rotated, audio-less and odd-sized
clips are covered by fixture tests without touching ffmpeg. Frame extraction writes a PNG sequence
and the stitcher re-encodes H.264 (yuv420p) at the source frame rate with the original audio,
copied when the codec fits MP4 and re-encoded to AAC when it does not. Rotation is honoured by
ffmpeg's auto-rotate on decode, so the frames are upright and the output carries no rotation tag.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Hard timeout for one ffmpeg/ffprobe run (extract of 60 s 1080p is well under a minute).
PROBE_TIMEOUT = 30.0
ENCODE_TIMEOUT = 1800.0
#: Container ``format_name`` values ffprobe prints (same table as the upload check).
CONTAINERS = {"mov,mp4,m4a,3gp,3g2,mj2": "mp4", "matroska,webm": "matroska"}
#: Audio codecs an MP4 can carry with ``-c:a copy``; anything else is re-encoded to AAC.
MP4_AUDIO_COPY = frozenset({"aac", "mp3", "ac3", "eac3", "alac"})
#: avg vs r frame rate may differ slightly on constant-rate files; more than this is VFR.
VFR_TOLERANCE = 0.02


class VideoError(ValueError):
    """The clip cannot be processed; the message is plain English and says what to do."""


@dataclass(frozen=True)
class AudioInfo:
    codec: str
    sample_rate: int
    channels: int


@dataclass(frozen=True)
class ClipInfo:
    """What the pipeline needs to know about the clip (from ffprobe, nothing guessed)."""

    container: str
    codec: str
    width: int
    height: int
    seconds: float
    #: Frame rate the frames are extracted and re-encoded at (constant).
    fps: float
    vfr: bool
    #: Display rotation in degrees (0, 90, 180, 270); frames are extracted upright.
    rotation: int
    audio: AudioInfo | None

    @property
    def even_size(self) -> tuple[int, int]:
        """Width/height rounded down to even (yuv420p needs even dimensions)."""
        return self.width - self.width % 2, self.height - self.height % 2


# ---------------------------------------------------------------------------------------------
# Pure parsing


def _rate(text: object) -> float:
    num, _, den = str(text or "0").partition("/")
    try:
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _rotation(stream: dict[str, object]) -> int:
    """Display rotation from the stream's side data (or its ``rotate`` tag), 0/90/180/270."""
    side = stream.get("side_data_list")
    degrees = 0.0
    if isinstance(side, list):
        for entry in side:
            if isinstance(entry, dict) and "rotation" in entry:
                try:
                    degrees = float(str(entry["rotation"]))
                except (TypeError, ValueError):
                    degrees = 0.0
                break
    else:
        tags = stream.get("tags")
        if isinstance(tags, dict):
            try:
                degrees = float(str(tags.get("rotate") or 0))
            except (TypeError, ValueError):
                degrees = 0.0
    return round(degrees / 90.0) % 4 * 90


def parse_probe(probe: dict[str, object]) -> ClipInfo:
    """ffprobe JSON (``-show_format -show_streams``) → ``ClipInfo``."""
    fmt = probe.get("format")
    streams = probe.get("streams")
    if not isinstance(fmt, dict) or not isinstance(streams, list):
        raise VideoError("This file is not a readable video.")
    container = CONTAINERS.get(str(fmt.get("format_name", "")))
    if container is None:
        raise VideoError("This video container is not supported. Use an MP4, MOV, MKV or WebM.")
    videos = [
        s
        for s in streams
        if isinstance(s, dict)
        and s.get("codec_type") == "video"
        and not (s.get("disposition") or {}).get("attached_pic")
    ]
    if not videos:
        raise VideoError("The file has no video track.")
    v = videos[0]
    try:
        width, height = _int(v.get("width")), _int(v.get("height"))
        seconds = float(str(fmt.get("duration") or v.get("duration") or 0))
    except (TypeError, ValueError) as exc:
        raise VideoError("The video's size or length cannot be read.") from exc
    if width <= 0 or height <= 0 or seconds <= 0:
        raise VideoError("The video's size or length cannot be read.")
    avg = _rate(v.get("avg_frame_rate"))
    r = _rate(v.get("r_frame_rate"))
    fps = avg or r
    if fps <= 0:
        raise VideoError("The video's frame rate cannot be read.")
    vfr = avg > 0 and r > 0 and abs(avg - r) / max(avg, r) > VFR_TOLERANCE
    audio: AudioInfo | None = None
    for s in streams:
        if isinstance(s, dict) and s.get("codec_type") == "audio":
            audio = AudioInfo(
                str(s.get("codec_name", "")),
                _int(s.get("sample_rate"), 44100),
                _int(s.get("channels"), 2),
            )
            break
    return ClipInfo(
        container=container,
        codec=str(v.get("codec_name", "")),
        width=width,
        height=height,
        seconds=seconds,
        fps=round(fps, 6),
        vfr=vfr,
        rotation=_rotation(v),
        audio=audio,
    )


# ---------------------------------------------------------------------------------------------
# Command builders (pure: argument lists, never shell strings)


def _binary(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise VideoError(
            f"{name} is not installed, so P11 cannot process videos. "
            "Install ffmpeg (`sudo pacman -S ffmpeg`)."
        )
    return found


def build_extract_cmd(
    ffmpeg: str,
    src: Path,
    frames_dir: Path,
    *,
    fps: float,
    start: float = 0.0,
    end: float | None = None,
    max_height: int | None = None,
    source_height: int = 0,
) -> list[str]:
    """Decode the clip to ``frames_dir/frame_%06d.png``, constant rate, upright (auto-rotate)."""
    out = frames_dir / "frame_%06d.png"
    args = [ffmpeg, "-nostdin", "-v", "error", "-y"]
    if start > 0:
        args += ["-ss", f"{start:.3f}"]
    if end is not None:
        args += ["-to", f"{end:.3f}"]
    args += ["-i", str(src), "-map", "0:v:0", "-an", "-sn", "-dn"]
    filters = [f"fps={fps:.6f}"]
    if max_height and source_height > max_height:
        filters.append(f"scale=-2:{max_height}")
    args += ["-vf", ",".join(filters), "-start_number", "1", str(out)]
    return args


def build_stitch_cmd(
    ffmpeg: str,
    frames_dir: Path,
    src: Path,
    dest: Path,
    *,
    fps: float,
    seconds: float,
    audio: AudioInfo | None,
    crf: int,
    start: float = 0.0,
) -> list[str]:
    """Re-encode the swapped PNGs to H.264 with the clip's own audio (copied or re-encoded)."""
    pattern = frames_dir / "frame_%06d.png"
    args = [ffmpeg, "-nostdin", "-v", "error", "-y", "-framerate", f"{fps:.6f}",
            "-start_number", "1", "-i", str(pattern)]  # fmt: skip
    if start > 0:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(src)]
    args += ["-map", "0:v:0", "-map", "1:a:0?", "-map_metadata", "-1", "-map_chapters", "-1"]
    args += ["-t", f"{seconds:.3f}"]
    # Odd frame sizes would break yuv420p; pad one pixel instead of rescaling.
    args += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2"]
    args += ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p"]
    if audio is not None and audio.codec in MP4_AUDIO_COPY:
        args += ["-c:a", "copy"]
    elif audio is not None:
        args += ["-c:a", "aac", "-b:a", "192k"]
    args += ["-movflags", "+faststart", str(dest)]
    return args


def build_probe_cmd(ffprobe: str, src: Path) -> list[str]:
    return [
        ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
        str(src),
    ]  # fmt: skip


def build_frame_cmd(
    ffmpeg: str, src: Path, dest: Path, *, at: float = 0.0, max_height: int | None = None
) -> list[str]:
    """One still frame (PNG) at ``at`` seconds, upright; used for the face picker and guard."""
    args = [ffmpeg, "-nostdin", "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", str(src),
            "-map", "0:v:0", "-frames:v", "1"]  # fmt: skip
    if max_height:
        args += ["-vf", f"scale=-2:{max_height}"]
    args += [str(dest)]
    return args


# ---------------------------------------------------------------------------------------------
# Running


def run(args: list[str], *, timeout: float, what: str) -> subprocess.CompletedProcess[bytes]:
    """Run one ffmpeg/ffprobe command (argument list, no shell) and check it worked."""
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise VideoError(f"{what} took too long.") from exc
    except OSError as exc:
        raise VideoError(f"{what} could not run: {exc}") from exc
    if r.returncode != 0:
        tail = (r.stderr or b"").decode(errors="replace").strip().splitlines()[-1:]
        detail = f" ({tail[0]})" if tail else ""
        raise VideoError(f"{what} failed{detail}.")
    return r


def ffmpeg_version() -> str:
    """The ffmpeg version in use (recorded in the benchmarks and the Phase Log)."""
    r = run([_binary("ffmpeg"), "-version"], timeout=PROBE_TIMEOUT, what="Checking ffmpeg")
    first = (r.stdout or b"").decode(errors="replace").splitlines()[:1]
    return first[0].split("Copyright")[0].strip() if first else "unknown"


def probe(src: Path) -> ClipInfo:
    r = run(
        build_probe_cmd(_binary("ffprobe"), src), timeout=PROBE_TIMEOUT, what="Checking the video"
    )
    try:
        data = json.loads(r.stdout or b"{}")
    except ValueError as exc:
        raise VideoError("This file is not a readable video.") from exc
    if not isinstance(data, dict):
        raise VideoError("This file is not a readable video.")
    return parse_probe(data)


def extract_frames(
    src: Path,
    frames_dir: Path,
    *,
    fps: float,
    start: float = 0.0,
    end: float | None = None,
    max_height: int | None = None,
    source_height: int = 0,
) -> list[Path]:
    """Extract the clip to numbered PNGs; returns the frame paths in order."""
    frames_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    frames_dir.chmod(0o700)
    for old in frames_dir.glob("frame_*.png"):
        old.unlink()
    run(
        build_extract_cmd(
            _binary("ffmpeg"),
            src,
            frames_dir,
            fps=fps,
            start=start,
            end=end,
            max_height=max_height,
            source_height=source_height,
        ),
        timeout=ENCODE_TIMEOUT,
        what="Extracting the video's frames",
    )
    return sorted(frames_dir.glob("frame_*.png"))


def stitch(
    frames_dir: Path,
    src: Path,
    dest: Path,
    *,
    fps: float,
    seconds: float,
    audio: AudioInfo | None,
    crf: int,
    start: float = 0.0,
) -> None:
    """Re-encode the (swapped) frame sequence to ``dest`` with the clip's own audio."""
    run(
        build_stitch_cmd(
            _binary("ffmpeg"),
            frames_dir,
            src,
            dest,
            fps=fps,
            seconds=seconds,
            audio=audio,
            crf=crf,
            start=start,
        ),
        timeout=ENCODE_TIMEOUT,
        what="Writing the finished video",
    )


def still_frame(src: Path, dest: Path, *, at: float = 0.0, max_height: int | None = None) -> Path:
    run(
        build_frame_cmd(_binary("ffmpeg"), src, dest, at=at, max_height=max_height),
        timeout=PROBE_TIMEOUT,
        what="Reading a frame from the video",
    )
    return dest


__all__ = [
    "AudioInfo",
    "ClipInfo",
    "VideoError",
    "build_extract_cmd",
    "build_frame_cmd",
    "build_probe_cmd",
    "build_stitch_cmd",
    "extract_frames",
    "ffmpeg_version",
    "parse_probe",
    "probe",
    "run",
    "still_frame",
    "stitch",
]

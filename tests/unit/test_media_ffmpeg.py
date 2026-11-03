"""``p11.media.ffmpeg``: ffprobe parsing fixtures and command builders (no shell, ever)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from p11.media.ffmpeg import (
    AudioInfo,
    VideoError,
    build_extract_cmd,
    build_frame_cmd,
    build_probe_cmd,
    build_stitch_cmd,
    extract_frames,
    ffmpeg_version,
    parse_probe,
    probe,
    still_frame,
    stitch,
)

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed"
)


def stream(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "avg_frame_rate": "30/1",
        "r_frame_rate": "30/1",
        "duration": "10.0",
    }
    base.update(over)
    return base


def probe_of(*streams: dict[str, object], **fmt: object) -> dict[str, object]:
    base: dict[str, object] = {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "10.0"}
    base.update(fmt)
    return {"format": base, "streams": list(streams)}


# -- parsing ---------------------------------------------------------------------------------


def test_parses_a_plain_mp4_with_audio():
    clip = parse_probe(
        probe_of(
            stream(),
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2},
        ),
    )
    assert (clip.container, clip.codec) == ("mp4", "h264")
    assert (clip.width, clip.height) == (1920, 1080)
    assert clip.seconds == 10.0 and clip.fps == 30.0
    assert clip.audio == AudioInfo("aac", 48000, 2)
    assert clip.rotation == 0 and not clip.vfr


def test_parses_matroska_and_a_missing_audio_track():
    clip = parse_probe(probe_of(stream(codec_name="vp9"), format_name="matroska,webm"))
    assert clip.container == "matroska" and clip.audio is None


def test_vfr_detection():
    vfr = parse_probe(probe_of(stream(avg_frame_rate="24000/1001", r_frame_rate="60/1")))
    assert vfr.vfr and vfr.fps == round(24000 / 1001, 6)
    cfr = parse_probe(probe_of(stream(avg_frame_rate="30000/1001", r_frame_rate="30000/1001")))
    assert not cfr.vfr
    close = parse_probe(probe_of(stream(avg_frame_rate="30/1", r_frame_rate="2997/100")))
    assert not close.vfr  # 1 % off is still constant rate


def test_rotation_from_side_data_or_tag():
    side = parse_probe(
        probe_of(stream(side_data_list=[{"side_data_type": "Display Matrix", "rotation": -90.0}]))
    )
    assert side.rotation == 270
    tagged = parse_probe(probe_of(stream(tags={"rotate": "90"})))
    assert tagged.rotation == 90
    assert parse_probe(probe_of(stream(side_data_list=[]))).rotation == 0


def test_odd_sizes_even_out():
    clip = parse_probe(probe_of(stream(width=641, height=361)))
    assert clip.even_size == (640, 360)


@pytest.mark.parametrize(
    "broken,match",
    [
        ({}, "not a readable video"),
        ({"format": {"format_name": "ogg"}, "streams": [stream()]}, "container"),
        (probe_of({"codec_type": "audio", "codec_name": "aac"}), "no video track"),
        (probe_of(stream(disposition={"attached_pic": 1})), "no video track"),
        (probe_of(stream(duration="0"), duration="0"), "size or length"),
        (probe_of(stream(avg_frame_rate="0/0", r_frame_rate="0/0")), "frame rate"),
    ],
)
def test_bad_probes_are_refused_with_plain_english(broken, match):  # type: ignore[no-untyped-def]
    with pytest.raises(VideoError, match=match):
        parse_probe(broken)


# -- command builders (argument lists: no shell, paths stay one argument each) -----------------


def test_extract_command_is_an_argument_list_with_trim_and_cap():
    src = Path("/tmp/clip; rm -rf ~.mp4")
    out = Path("/tmp/frames dir")
    args = build_extract_cmd(
        "ffmpeg", src, out, fps=29.97, start=1.5, end=4.0, max_height=720, source_height=1080
    )
    assert args[0] == "ffmpeg" and "-nostdin" in args and "-y" in args
    assert args[args.index("-ss") + 1] == "1.500"
    assert args[args.index("-to") + 1] == "4.000"
    # every path is its own argument; nothing is quoted or joined into a command line
    assert str(src) in args and args[-1] == str(out / "frame_%06d.png")
    assert all(isinstance(a, str) for a in args)
    vf = args[args.index("-vf") + 1]
    assert vf == "fps=29.970000,scale=-2:720"
    assert "-an" in args and args[args.index("-map") + 1] == "0:v:0"


def test_extract_command_without_caps_has_no_scale_filter():
    args = build_extract_cmd("ffmpeg", Path("in.mp4"), Path("f"), fps=30.0, source_height=720)
    assert args[args.index("-vf") + 1] == "fps=30.000000"
    assert "-ss" not in args and "-to" not in args


def test_stitch_command_copies_compatible_audio_and_trims_it():
    args = build_stitch_cmd(
        "ffmpeg", Path("frames"), Path("in.mp4"), Path("out.mp4"),
        fps=30.0, seconds=2.5, audio=AudioInfo("aac", 48000, 2), crf=18, start=1.5,
    )  # fmt: skip
    assert args[args.index("-framerate") + 1] == "30.000000"
    assert args[args.index("-ss") + 1] == "1.500"  # the audio starts where the trim starts
    assert args[args.index("-t") + 1] == "2.500"
    assert args[args.index("-c:a") + 1] == "copy"
    assert args[args.index("-c:v") + 1] == "libx264"
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"
    assert args[args.index("-vf") + 1] == "pad=ceil(iw/2)*2:ceil(ih/2)*2"
    assert "-map_metadata" in args and args[args.index("-map_metadata") + 1] == "-1"
    assert args[-1] == "out.mp4"


def test_stitch_command_re_encodes_incompatible_audio():
    args = build_stitch_cmd(
        "ffmpeg", Path("frames"), Path("in.mkv"), Path("out.mp4"),
        fps=25.0, seconds=3.0, audio=AudioInfo("opus", 48000, 2), crf=23,
    )  # fmt: skip
    assert args[args.index("-c:a") + 1] == "aac"
    assert "-ss" not in args
    no_audio = build_stitch_cmd(
        "ffmpeg", Path("frames"), Path("in.mp4"), Path("out.mp4"),
        fps=25.0, seconds=3.0, audio=None, crf=23,
    )  # fmt: skip
    assert "-c:a" not in no_audio


def test_frame_and_probe_commands():
    frame = build_frame_cmd("ffmpeg", Path("in.mp4"), Path("f.png"), at=2.0, max_height=480)
    assert frame[frame.index("-ss") + 1] == "2.000" and frame[-1] == "f.png"
    assert frame[frame.index("-vf") + 1] == "scale=-2:480"
    probing = build_probe_cmd("ffprobe", Path("in.mp4"))
    assert "-show_streams" in probing and "-print_format" in probing


# -- the real tools (small synthetic clips only) -----------------------------------------------


def make_clip(path: Path, *, seconds: float = 1.0, size: str = "160x120",
              rate: int = 10, audio: bool = True) -> Path:  # fmt: skip
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
            f"testsrc=size={size}:rate={rate}:duration={seconds}"]  # fmt: skip
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac", "-shortest"]
    subprocess.run([*args, str(path)], check=True, capture_output=True)
    return path


@needs_ffmpeg
def test_probe_extracts_and_stitches_a_real_clip(tmp_path):
    src = make_clip(tmp_path / "clip.mp4")
    clip = probe(src)
    assert (clip.width, clip.height) == (160, 120) and abs(clip.fps - 10) < 0.5
    assert clip.audio is not None and clip.audio.codec == "aac" and not clip.vfr
    frames = extract_frames(src, tmp_path / "frames", fps=clip.fps, source_height=clip.height)
    assert len(frames) == 10 and frames[0].name == "frame_000001.png"
    dest = tmp_path / "out.mp4"
    stitch(tmp_path / "frames", src, dest, fps=clip.fps, seconds=1.0,
           audio=clip.audio, crf=23)  # fmt: skip
    out = probe(dest)
    assert (out.width, out.height) == (160, 120) and out.seconds > 0.8
    assert out.audio is not None and out.audio.codec == "aac"


@needs_ffmpeg
def test_extract_trims_and_downscales(tmp_path):
    src = make_clip(tmp_path / "clip.mp4", seconds=2.0)
    frames = extract_frames(src, tmp_path / "frames", fps=10.0, start=0.5, end=1.5,
                            max_height=60, source_height=120)  # fmt: skip
    assert len(frames) == 10
    from PIL import Image

    with Image.open(frames[0]) as img:
        assert img.size == (80, 60)


@needs_ffmpeg
def test_still_frame_and_version(tmp_path):
    src = make_clip(tmp_path / "clip.mp4")
    still = still_frame(src, tmp_path / "still.png", at=0.5)
    assert still.is_file() and still.stat().st_size > 0
    assert ffmpeg_version().startswith("ffmpeg version")


@needs_ffmpeg
def test_unreadable_files_get_plain_english_errors(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video at all")
    with pytest.raises(VideoError, match="Checking the video failed"):
        probe(bad)
    with pytest.raises(VideoError, match="Extracting the video's frames failed"):
        extract_frames(tmp_path / "missing.mp4", tmp_path / "frames", fps=10.0)

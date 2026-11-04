"""ComfyEngine pieces that need no engine: config, command line, parsers, error mapping."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from tests.engine_contract import synthetic_png
from tests.unit.test_engine_contract import mock_config

from p11.config import load_settings
from p11.engine import create_engine
from p11.engine.base import (
    EngineCrashed,
    EngineExecutionError,
    EngineFileRef,
    EngineOOM,
    EngineUnavailable,
    EngineValidation,
    bind_inputs,
    graph_nodes,
    is_oom_message,
    stamp_output_prefixes,
    upload_name,
)
from p11.engine.comfy import (
    VRAM_FLAGS,
    ComfyEngine,
    EngineConfig,
    parse_preview,
    parse_prompt_error,
    parse_system_stats,
)
from p11.engine.fake import FakeEngine
from p11.engine.lockfile import find_lock_file, load_lock
from p11.recipe.compile import EngineGraph, GraphInput


def test_lock_matches_engine_lock_toml() -> None:
    lock = load_lock()
    assert lock.version == "0.43.0" and lock.commit.startswith("426f5ee")
    assert lock.listen == "127.0.0.1" and "--offline" in lock.flags


def test_lock_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("P11_ENGINE_LOCK", str(tmp_path / "x.toml"))
    assert find_lock_file() == tmp_path / "x.toml"


def test_default_config_uses_p11_paths() -> None:
    cfg = EngineConfig.default(load_settings(engine_port=8199))
    assert cfg.port == 8199
    assert cfg.log_path.name == "engine.log" and cfg.log_path.parent.name == "logs"
    assert cfg.lock_path is not None and cfg.lock_path.name == "gpu.lock"


@pytest.mark.parametrize("mode", ["dynamic", "lowvram"])
def test_command_is_loopback_and_offline(mode: str, tmp_path: Path) -> None:
    cfg = mock_config(tmp_path)
    cmd = cfg.command(mode)  # type: ignore[arg-type]
    assert cmd[1] == "main.py"
    assert cmd[cmd.index("--listen") + 1] == "127.0.0.1"
    assert cmd[cmd.index("--port") + 1] == str(cfg.port)
    for flag in ("--offline", "--disable-all-custom-nodes", "--disable-auto-launch"):
        assert flag in cmd
    assert cmd[-len(VRAM_FLAGS[mode]) :] == list(VRAM_FLAGS[mode]) or not VRAM_FLAGS[mode]  # type: ignore[index]


def test_parse_system_stats() -> None:
    body = {
        "system": {"comfyui_version": "0.43.0", "ram_total": 5, "argv": ["main.py", "--listen"]},
        "devices": [{"name": "cuda:0", "type": "cuda", "vram_total": 8, "vram_free": 7}],
    }
    s = parse_system_stats(body)
    assert s.version == "0.43.0" and s.argv == ("main.py", "--listen")
    assert s.devices[0].vram_free == 7 and s.devices[0].torch_vram_free == 0


def test_parse_prompt_error_node() -> None:
    body = {
        "error": {"type": "prompt_outputs_failed_validation", "message": "failed"},
        "node_errors": {
            "3": {
                "errors": [{"message": "Value not in list", "details": "ckpt_name: 'x'"}],
                "class_type": "CheckpointLoaderSimple",
            }
        },
    }
    assert parse_prompt_error(body) == (
        "3",
        "CheckpointLoaderSimple: Value not in list (ckpt_name: 'x')",
    )


def test_parse_prompt_error_global() -> None:
    body = {"error": {"type": "invalid_prompt", "message": "Cannot execute", "details": "why"}}
    assert parse_prompt_error(body) == (None, "Cannot execute (why)")
    assert parse_prompt_error({"error": "plain"}) == (None, "plain")
    assert parse_prompt_error({}) == (None, "invalid prompt")


def test_parse_preview_frames() -> None:
    assert parse_preview(struct.pack(">II", 1, 1) + b"jpg", "p") is not None
    png = parse_preview(struct.pack(">II", 1, 2) + b"png", "p")
    assert png is not None and png.mime == "image/png" and png.data == b"png"
    meta = json.dumps({"prompt_id": "p", "image_type": "image/png"}).encode()
    framed = struct.pack(">II", 4, len(meta)) + meta + b"img"
    got = parse_preview(framed, "p")
    assert got is not None and got.data == b"img"
    assert parse_preview(framed, "other") is None
    assert parse_preview(struct.pack(">II", 4, 3) + b"{x}", "p") is None
    assert parse_preview(struct.pack(">II", 3, 0), "p") is None
    assert parse_preview(b"x", "p") is None


def test_upload_name_is_content_addressed() -> None:
    data = synthetic_png(8, 8)
    name, mime = upload_name(data, "mask")
    assert name.startswith("p11-mask-") and name.endswith(".png") and mime == "image/png"
    assert upload_name(data, "mask") == (name, mime)
    with pytest.raises(EngineValidation):
        upload_name(b"not an image", "image")


def test_is_oom_message() -> None:
    # comfy-aimdo (dynamic VRAM) reports a failed growth this way (Phase 11 follow-up).
    assert is_oom_message("RuntimeError", "VRAM grow failed")
    assert is_oom_message("torch.OutOfMemoryError", "")
    assert is_oom_message("RuntimeError", "CUDA error: out of memory")
    assert not is_oom_message("RuntimeError", "mat1 and mat2 shapes")


def test_graph_nodes_rejects_non_api_nodes() -> None:
    with pytest.raises(EngineValidation, match="class_type"):
        graph_nodes({"1": {"inputs": {}}})


def test_stamp_output_prefixes_gives_each_run_its_own_files() -> None:
    """ComfyUI caches node outputs across prompts; a repeated graph must still write a file
    (ADR-0042): the token is in the cache key, so ``SaveImage`` re-runs and names its own file."""
    nodes = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "a.safetensors"}},
        "13": {
            "class_type": "SaveImage",
            "inputs": {"images": ["1", 0], "filename_prefix": "p11/step-00"},
        },
    }
    first = stamp_output_prefixes(nodes, "49747701")
    second = stamp_output_prefixes(nodes, "0fbc1fa1")
    assert first["13"]["inputs"]["filename_prefix"] == "p11/step-00-49747701"
    assert second["13"]["inputs"]["filename_prefix"] == "p11/step-00-0fbc1fa1"
    assert first["13"]["inputs"] != second["13"]["inputs"]  # a different cache key per run
    assert first["1"] == nodes["1"] and first["13"]["inputs"]["images"] == ["1", 0]
    # The caller's graph is untouched (EngineGraph.nodes is reused across runs).
    assert nodes["13"]["inputs"]["filename_prefix"] == "p11/step-00"


def test_stamp_output_prefixes_ignores_other_nodes() -> None:
    nodes = {
        "1": {"class_type": "PreviewImage", "inputs": {"filename_prefix": "p11/x"}},
        "2": {"class_type": "SaveImage", "inputs": {"filename_prefix": 7}},
        "3": {"class_type": "SaveImage", "inputs": {}},
        "4": {"class_type": "SaveImage"},
    }
    assert all(v == nodes[k] for k, v in stamp_output_prefixes(nodes, "ab").items())


def test_bind_inputs_requires_every_placeholder() -> None:
    g = EngineGraph(
        0,
        "x",
        {"5": {"class_type": "LoadImage", "inputs": {"image": "p11:source"}}},
        "5",
        (GraphInput("5", "source", "p11:source"),),
        (),
        1,
        None,
    )
    with pytest.raises(EngineValidation, match="no upload bound"):
        bind_inputs(g, {})
    nodes = bind_inputs(g, {"p11:source": EngineFileRef("a.png", subfolder="p11")})
    assert nodes["5"]["inputs"]["image"] == "p11/a.png"
    assert g.nodes["5"]["inputs"]["image"] == "p11:source"  # not mutated


def test_create_engine() -> None:
    assert isinstance(create_engine(load_settings(), fake=True), FakeEngine)
    assert isinstance(create_engine(load_settings()), ComfyEngine)


async def test_start_refuses_missing_install(tmp_path: Path) -> None:
    from dataclasses import replace

    cfg = replace(mock_config(tmp_path), engine_dir=tmp_path / "nothing")
    engine = ComfyEngine(cfg)
    with pytest.raises(EngineUnavailable, match="not installed"):
        await engine.start()
    await engine.aclose()


async def test_requests_before_start_are_unavailable(tmp_path: Path) -> None:
    engine = ComfyEngine(mock_config(tmp_path))
    try:
        with pytest.raises(EngineUnavailable):
            await engine.run({"1": {"class_type": "SaveImage", "inputs": {}}})
        with pytest.raises(EngineUnavailable):
            await engine.upload(synthetic_png(8, 8))
        with pytest.raises(EngineUnavailable):
            await engine.system_stats()
        assert (await engine.health()).state == "stopped"
        await engine.interrupt()  # harmless when stopped
    finally:
        await engine.aclose()


async def test_version_mismatch_is_refused(tmp_path: Path) -> None:
    from dataclasses import replace

    cfg = mock_config(tmp_path)
    cfg = replace(cfg, lock=replace(cfg.lock, tag="v9.9.9"))
    engine = ComfyEngine(cfg)
    with pytest.raises(EngineUnavailable, match=r"pinned to 9\.9\.9"):
        await engine.start()
    assert not engine.supervisor.running
    await engine.aclose()


async def test_mock_errors_map_to_typed_errors(tmp_path: Path) -> None:
    import httpx
    from tests.engine_contract import generate_graph

    engine = ComfyEngine(mock_config(tmp_path))
    await engine.start()
    try:
        async with httpx.AsyncClient(base_url=engine.base_url) as c:
            await c.post("/mock/fail", json={"kind": "oom"})
            with pytest.raises(EngineOOM, match="Out of GPU memory"):
                await engine.run(generate_graph("1:1-1024"))
            await c.post("/mock/fail", json={"kind": "execution"})
            with pytest.raises(EngineExecutionError, match="simulated failure"):
                await engine.run(generate_graph("1:1-1024"))
        from p11.engine.base import EngineTimeout

        with pytest.raises(EngineTimeout, match="longer than"):
            await engine.run(generate_graph("16:9-1920x1080"), timeout=0.05)
        assert (await engine.health()).ready
        # A crash mid-run surfaces as EngineCrashed.
        import asyncio
        import os
        import signal

        task = asyncio.create_task(engine.run(generate_graph("16:9-1920x1080", seed=3)))
        await asyncio.sleep(0.3)
        pid = engine.supervisor.pid
        assert pid is not None
        os.killpg(pid, signal.SIGKILL)
        with pytest.raises(EngineCrashed):
            await task
    finally:
        await engine.aclose()


async def test_outputs_are_deleted_from_engine_scratch(tmp_path: Path) -> None:
    engine = ComfyEngine(mock_config(tmp_path))
    out = engine.config.output_dir / "p11"
    out.mkdir(parents=True)
    (out / "keep.txt").write_text("x")
    engine._delete_output("p11", "keep.txt")
    engine._delete_output("..", "..")  # outside the output dir: ignored
    assert not (out / "keep.txt").exists()
    await engine.aclose()

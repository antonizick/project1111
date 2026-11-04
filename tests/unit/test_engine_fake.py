"""FakeEngine behaviour beyond the contract: golden graphs, validation, failures, OOM retry."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest
from PIL import Image
from tests.engine_contract import generate_graph, resized, synthetic_png

from p11.engine.base import (
    EngineCrashed,
    EngineInterrupted,
    EngineOOM,
    EngineTimeout,
    EngineUnavailable,
    EngineValidation,
    Retrying,
)
from p11.engine.fake import KNOWN_NODES, FakeConfig, FakeEngine
from p11.engine.recovery import OOM_MESSAGE, run_with_oom_retry

REPO = Path(__file__).resolve().parents[2]
GOLDEN_ALL = sorted((REPO / "tests/golden/compile").glob("*.json"))
# Goldens whose LoadImage/LoadImageMask placeholders are bound to uploads before running.
# Photo-edit goldens (`img2img__`, Phase 17b) run in `test_photo_edit.py` with their photo bound.
GOLDEN = [
    p for p in GOLDEN_ALL if not p.stem.startswith(("inpaint__", "background__", "img2img__"))
]
INPAINT_GOLDEN = [p for p in GOLDEN_ALL if p.stem.startswith(("inpaint__", "background__"))]


@pytest.fixture
async def fake() -> FakeEngine:
    f = FakeEngine()
    await f.start()
    return f


def test_known_nodes_cover_the_compiler() -> None:
    sources = [REPO / "src/p11/recipe/compile.py", *(REPO / "src/p11/recipe/steps").glob("*.py")]
    source = "\n".join(p.read_text() for p in sources)
    used = set(re.findall(r'g\.node\(\s*"([A-Za-z0-9]+)"', source))
    used |= set(re.findall(r'_tiled\(\s*g,\s*"([A-Za-z0-9]+)"', source))
    assert used, "compiler node names not found"
    assert used <= KNOWN_NODES, used - KNOWN_NODES


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.stem)
async def test_golden_graphs_run(fake: FakeEngine, path: Path) -> None:
    nodes = json.loads(path.read_text())
    save = next(k for k, v in nodes.items() if v["class_type"] == "SaveImage")
    result = await fake.run(nodes)
    (image,) = result.images
    assert image.node == save
    with Image.open(io.BytesIO(image.data)) as img:
        w, h = img.size
    scale = next((v for v in nodes.values() if v["class_type"] == "ImageScale"), None)
    if scale:
        assert (w, h) == (scale["inputs"]["width"], scale["inputs"]["height"])
    else:
        latent = next(v for v in nodes.values() if v["class_type"] == "EmptyLatentImage")
        assert (w, h) == (latent["inputs"]["width"], latent["inputs"]["height"])


@pytest.mark.parametrize("path", INPAINT_GOLDEN, ids=lambda p: p.stem)
async def test_inpaint_golden_graphs_run(fake: FakeEngine, path: Path) -> None:
    """Inpaint and background goldens run once their placeholders are bound to uploads."""
    nodes = json.loads(path.read_text())
    image = await fake.upload(synthetic_png(64, 48), "image")
    mask = await fake.upload(synthetic_png(64, 48), "mask")
    for node in nodes.values():
        value = node["inputs"].get("image")
        if node["class_type"] == "LoadImage" and str(value).startswith("p11:"):
            node["inputs"]["image"] = image.name
        if node["class_type"] == "LoadImageMask":
            node["inputs"]["image"] = mask.name
    result = await fake.run(nodes)
    (out,) = result.images
    with Image.open(io.BytesIO(out.data)) as img:
        assert img.size == (64, 48)


async def test_output_is_deterministic_per_seed(fake: FakeEngine) -> None:
    a = await fake.run(generate_graph("1:1-1024", seed=1))
    b = await fake.run(generate_graph("1:1-1024", seed=1))
    c = await fake.run(generate_graph("1:1-1024", seed=2))
    assert a.images[0].data == b.images[0].data != c.images[0].data


async def test_model_list_validation() -> None:
    f = FakeEngine(FakeConfig(models={"other.safetensors"}))
    await f.start()
    with pytest.raises(EngineValidation, match="Value not in list: ckpt_name"):
        await f.run(generate_graph())


@pytest.mark.parametrize(
    ("nodes", "match"),
    [
        ({"1": {"class_type": "CLIPTextEncode", "inputs": {}}}, "no outputs"),
        ({"1": {"class_type": "SaveImage", "inputs": {"images": ["9", 0]}}}, "missing node"),
        (
            {
                "1": {"class_type": "LoadImage", "inputs": {"image": "nope.png"}},
                "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
            },
            "Invalid image",
        ),
        (
            {
                "1": {"class_type": "ImageInvert", "inputs": {"image": ["2", 0]}},
                "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
            },
            "cycle",
        ),
    ],
)
async def test_validation_errors(fake: FakeEngine, nodes: dict, match: str) -> None:  # type: ignore[type-arg]
    with pytest.raises(EngineValidation, match=match):
        await fake.run(nodes)


async def test_simulated_validation_and_not_started() -> None:
    f = FakeEngine()
    with pytest.raises(EngineUnavailable):
        await f.run(generate_graph())
    await f.start()
    f.fail_next("validation")
    with pytest.raises(EngineValidation, match="simulated"):
        await f.run(generate_graph())
    assert len((await f.run(generate_graph())).images) == 1


async def test_size_inference_for_upscale_chains(fake: FakeEngine) -> None:
    ref = await fake.upload(synthetic_png(300, 200))
    nodes = {
        "1": {"class_type": "LoadImage", "inputs": {"image": ref.name}},
        "2": {"class_type": "ImageScaleBy", "inputs": {"image": ["1", 0], "scale_by": 1.5}},
        "3": {"class_type": "ImageScale", "inputs": {"image": ["2", 0], "width": 900, "height": 0}},
        "4": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "x"}},
        "5": {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {"image": ["3", 0], "upscale_model": ["4", 0]},
        },
        "6": {"class_type": "SaveImage", "inputs": {"images": ["5", 0]}},
        "7": {
            "class_type": "SaveImage",
            "inputs": {"images": ["2", 0], "filename_prefix": "p11/b"},
        },
    }
    result = await fake.run(nodes)
    sizes = {i.node: Image.open(io.BytesIO(i.data)).size for i in result.images}
    assert sizes == {"6": (3600, 2400), "7": (450, 300)}


async def test_crash_during_run_restarts_once() -> None:
    f = FakeEngine()
    await f.start()
    f.fail_next("crash")
    with pytest.raises(EngineCrashed):
        await f.run(generate_graph())
    await f.stop()
    await f.start()
    f.crash()
    assert (await f.health()).state == "crashed"
    with pytest.raises(EngineCrashed):
        await f.free_memory()
    await f._restart_task  # type: ignore[misc]
    assert (await f.health()).ready and f.restarts == 1
    f.crash()  # second crash: no more restarts
    assert (await f.health()).state == "crashed"
    await f.stop()


async def test_timeout_and_interrupt_when_idle() -> None:
    f = FakeEngine(FakeConfig(step_delay=0.05))
    await f.start()
    await f.interrupt()  # nothing running: no effect on the next run
    with pytest.raises(EngineTimeout):
        await f.run(generate_graph(), timeout=0.05)
    assert len((await f.run(generate_graph(), timeout=30)).images) == 1


async def test_interrupt_from_event_callback() -> None:
    f = FakeEngine(FakeConfig(step_delay=0.01))
    await f.start()

    async def on_event(ev: object) -> None:
        if getattr(ev, "type", "") == "progress":
            await f.interrupt()

    with pytest.raises(EngineInterrupted):
        await f.run(generate_graph(), on_event=on_event)


async def test_oom_retry_fails_with_plain_message(fake: FakeEngine) -> None:
    events: list[object] = []
    with pytest.raises(EngineOOM) as exc:
        await run_with_oom_retry(fake, resized(generate_graph(), 4096), on_event=events.append)
    assert str(exc.value) == OOM_MESSAGE
    assert fake.free_calls == [True] and fake.vram_mode == "lowvram"
    assert any(isinstance(e, Retrying) for e in events)


async def test_oom_retry_not_needed(fake: FakeEngine) -> None:
    result = await run_with_oom_retry(fake, generate_graph())
    assert not result.retried and fake.free_calls == [] and fake.vram_mode == "dynamic"


async def test_oom_retry_already_low_vram() -> None:
    f = FakeEngine(vram_mode="lowvram")
    await f.start()
    f.fail_next("oom")
    result = await run_with_oom_retry(f, generate_graph())
    assert result.retried and f.starts == 1  # no restart needed


async def test_system_stats_and_health(fake: FakeEngine) -> None:
    stats = await fake.system_stats()
    assert stats.version == "0.43.0" and stats.devices[0].vram_total == 8 * 1024**3
    health = await fake.health()
    assert health.ready and health.vram_mode == "dynamic" and health.version == "0.43.0"

"""The ``Engine`` contract suite (Phase 05), shared by every implementation.

``tests/unit/test_engine_contract.py`` runs it against ``FakeEngine`` and against ``ComfyEngine``
over the mock ComfyUI server; ``tests/gpu/test_engine_contract_gpu.py`` runs it against the real
pinned engine on the laptop. Each check takes a ``Harness`` that knows how to build graphs for
its engine and how to kill it.
"""

from __future__ import annotations

import asyncio
import io
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from PIL import Image
from tests.helpers import recipe

from p11.engine.base import (
    Engine,
    EngineEvent,
    EngineInterrupted,
    EngineOOM,
    EngineValidation,
    Executed,
    Executing,
    Progress,
    Queued,
    Retrying,
    bind_inputs,
)
from p11.engine.recovery import OOM_MESSAGE, run_with_oom_retry
from p11.recipe.compile import EngineGraph, compile
from p11.recipe.model import Generate
from p11.recipe.registry import PROVISIONAL_DEFAULT_SET


@dataclass
class Harness:
    engine: Engine
    #: Kill the engine process abruptly (the supervisor should restart it once).
    kill: Callable[[], Awaitable[None]]
    #: Latent edge (pixels) that runs out of memory in the default VRAM mode.
    oom_edge: int = 2560
    #: ``True`` if the OOM graph must recover in low-VRAM mode, ``None`` if either outcome is OK.
    oom_recovers: bool | None = True
    interrupt_limit: float = 2.0
    ready_timeout: float = 30.0
    extra: dict[str, Any] = field(default_factory=dict)


class Recorder:
    def __init__(self) -> None:
        self.events: list[EngineEvent] = []
        self.first_progress = asyncio.Event()

    def __call__(self, ev: EngineEvent) -> None:
        self.events.append(ev)
        if isinstance(ev, Progress):
            self.first_progress.set()

    def of(self, cls: type) -> list[Any]:
        return [e for e in self.events if isinstance(e, cls)]


def generate_graph(aspect: str = "1:1-1024", seed: int = 1111) -> EngineGraph:
    r = recipe(Generate(prompt="a lighthouse on a rocky coast at dusk", aspect=aspect))
    (graph,) = compile(r, {}, PROVISIONAL_DEFAULT_SET, seed=seed)
    return graph


def resized(graph: EngineGraph, edge: int) -> dict[str, Any]:
    """``graph`` with its base latent set to ``edge`` x ``edge`` (the forced-OOM graph)."""
    nodes = {k: {**v, "inputs": dict(v["inputs"])} for k, v in graph.nodes.items()}
    for node in nodes.values():
        if node["class_type"] == "EmptyLatentImage":
            node["inputs"].update(width=edge, height=edge)
    return nodes


def img2img_graph(graph: EngineGraph, image_name: str, denoise: float = 0.5) -> dict[str, Any]:
    """LoadImage → VAEEncode → KSampler (denoise) → VAEDecode → SaveImage, models from ``graph``."""
    ckpt = next(v for v in graph.nodes.values() if v["class_type"] == "CheckpointLoaderSimple")
    vae = next(v for v in graph.nodes.values() if v["class_type"] == "VAELoader")
    base = next(v for v in graph.nodes.values() if v["class_type"] == "KSampler")
    s = base["inputs"]
    return {
        "1": ckpt,
        "2": vae,
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": "oil painting"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": "blurry"}},
        "5": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "6": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["2", 0]}},
        "7": {
            "class_type": "KSampler",
            "_meta": {"title": "base"},
            "inputs": {
                "model": ["1", 0],
                "positive": ["3", 0],
                "negative": ["4", 0],
                "latent_image": ["6", 0],
                "seed": 7,
                "steps": s["steps"],
                "cfg": s["cfg"],
                "sampler_name": s["sampler_name"],
                "scheduler": s["scheduler"],
                "denoise": denoise,
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["2", 0]}},
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "p11/i2i"},
        },
    }


def synthetic_png(w: int, h: int) -> bytes:
    """A gradient test image (synthetic, S6)."""
    img = Image.new("RGB", (w, h))
    img.putdata([(x * 255 // w, y * 255 // h, 128) for y in range(h) for x in range(w)])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def png_size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as img:
        assert img.format == "PNG"
        return img.size


async def wait_ready(h: Harness) -> None:
    deadline = time.monotonic() + h.ready_timeout
    while time.monotonic() < deadline:
        if (await h.engine.health()).ready:
            return
        await asyncio.sleep(0.2)
    pytest.fail(f"engine not ready after {h.ready_timeout}s: {await h.engine.health()}")


# ---------------------------------------------------------------------------------------------
# Checks.


async def check_generate(h: Harness, aspect: str = "16:9-1920x1080", seed: int = 1111) -> None:
    graph = generate_graph(aspect, seed)
    rec = Recorder()
    result = await h.engine.run(graph, on_event=rec)
    (image,) = result.images
    assert image.node == graph.output_node
    assert png_size(image.data) == graph.size
    assert isinstance(rec.events[0], Queued) and rec.events[0].prompt_id == result.prompt_id
    progress = rec.of(Progress)
    assert progress and all(p.title == "base" for p in progress if p.node == "6")
    assert progress[-1].step == progress[-1].total
    assert any(e.node == "6" and e.title == "base" for e in rec.of(Executing))
    assert [e.node for e in rec.of(Executed)][-1] == graph.output_node
    assert result.seconds > 0


async def check_interrupt(h: Harness) -> None:
    graph = generate_graph("16:9-1920x1080", seed=4242)
    rec = Recorder()
    task = asyncio.create_task(h.engine.run(graph, on_event=rec))
    await asyncio.wait_for(rec.first_progress.wait(), 120)
    t0 = time.monotonic()
    await h.engine.interrupt()
    with pytest.raises(EngineInterrupted):
        await task
    took = time.monotonic() - t0
    assert took < h.interrupt_limit, f"interrupt took {took:.2f}s"
    # The engine is still usable afterwards.
    result = await h.engine.run(generate_graph("1:1-1024", seed=4243))
    assert len(result.images) == 1


async def check_upload_img2img(h: Harness) -> None:
    ref = await h.engine.upload(synthetic_png(768, 512))
    assert ref.name.startswith("p11-image-") and ref.name.endswith(".png")
    again = await h.engine.upload(synthetic_png(768, 512))
    assert again == ref  # content-addressed
    result = await h.engine.run(img2img_graph(generate_graph(), ref.node_value))
    (image,) = result.images
    assert png_size(image.data) == (768, 512)


async def check_bind_inputs(h: Harness) -> None:
    from p11.recipe.compile import GraphInput

    base = generate_graph()
    nodes = img2img_graph(base, "p11:slot:photo")
    inp = GraphInput("5", "slot", "p11:slot:photo", slot="photo")
    graph = EngineGraph(0, "img2img", nodes, "9", (inp,), (), 7, (768, 512))
    with pytest.raises(EngineValidation, match="placeholder"):
        await h.engine.run(graph)
    ref = await h.engine.upload(synthetic_png(768, 512))
    result = await h.engine.run(bind_inputs(graph, {"p11:slot:photo": ref}))
    assert png_size(result.images[0].data) == (768, 512)


async def check_validation(h: Harness) -> None:
    graph = generate_graph()
    nodes = {k: dict(v) for k, v in graph.nodes.items()}
    nodes["3"] = {**nodes["3"], "class_type": "NoSuchNodeP11"}
    with pytest.raises(EngineValidation) as exc:
        await h.engine.run(nodes)
    assert exc.value.node == "3" or "NoSuchNodeP11" in str(exc.value)
    assert (await h.engine.health()).ready


async def check_free_memory(h: Harness) -> None:
    await h.engine.run(generate_graph("1:1-1024", seed=99))
    await h.engine.free_memory(unload_models=True)
    stats = await h.engine.system_stats()
    assert stats.devices and stats.devices[0].vram_total > 0
    result = await h.engine.run(generate_graph("1:1-1024", seed=100))
    assert len(result.images) == 1


async def check_oom_recovery(h: Harness) -> None:
    oversized = resized(generate_graph("1:1-1024", seed=5), h.oom_edge)
    rec = Recorder()
    try:
        result = await run_with_oom_retry(h.engine, oversized, on_event=rec, timeout=900)
    except EngineOOM as exc:
        assert h.oom_recovers is not True, "expected the low-VRAM retry to succeed"
        assert str(exc) == OOM_MESSAGE
        assert rec.of(Retrying)
    else:
        assert h.oom_recovers is not False, "expected the retry to fail too"
        assert result.retried and result.vram_mode == "lowvram"
        assert rec.of(Retrying)
    assert h.engine.vram_mode == "lowvram"
    # The engine recovers: a normal image works afterwards, then back to the default mode.
    result = await h.engine.run(generate_graph("1:1-1024", seed=6))
    assert len(result.images) == 1
    await h.engine.restart("dynamic")
    assert h.engine.vram_mode == "dynamic"


async def check_crash_restart(h: Harness) -> None:
    before = (await h.engine.health()).restarts
    await h.kill()
    await wait_ready(h)
    health = await h.engine.health()
    assert health.restarts == before + 1
    result = await h.engine.run(generate_graph("1:1-1024", seed=8))
    assert len(result.images) == 1


CHECKS: dict[str, Callable[[Harness], Awaitable[None]]] = {
    "generate": check_generate,
    "interrupt": check_interrupt,
    "upload_img2img": check_upload_img2img,
    "bind_inputs": check_bind_inputs,
    "validation": check_validation,
    "free_memory": check_free_memory,
    "oom_recovery": check_oom_recovery,
    "crash_restart": check_crash_restart,
}

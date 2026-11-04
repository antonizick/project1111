"""``FakeEngine``: the ``Engine`` protocol without a GPU (tests and ``p11 serve --fake``).

It validates graphs like ComfyUI's ``/prompt`` does (known node types, links, uploaded images,
optionally the model list), emits the same event sequence (queued → executing/progress per node →
executed for each output node), writes deterministic placeholder PNGs (the size the graph would
produce, the seed drawn on the image) and can simulate OOM, validation errors, crashes, failures
and slow runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import time
import uuid
from collections import deque
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageDraw

from p11.engine.base import (
    DeviceStats,
    EngineCrashed,
    EngineExecutionError,
    EngineFileRef,
    EngineHealth,
    EngineInterrupted,
    EngineOOM,
    EngineState,
    EngineTimeout,
    EngineUnavailable,
    EngineValidation,
    EventCallback,
    Executed,
    Executing,
    OutputImage,
    Progress,
    Queued,
    RunResult,
    SystemStats,
    UploadKind,
    VramMode,
    emit,
    graph_nodes,
    node_titles,
    upload_name,
)
from p11.recipe.compile import EngineGraph

#: Node types the fake accepts. Each was checked to exist in ComfyUI v0.43.0 ``426f5ee``
#: (``nodes.py``, ``comfy_extras/nodes_upscale_model.py``, ``comfy_extras/nodes_mask.py``) on
#: 2026-11-02 18:45 CST (``RepeatLatentBatch``: 2026-11-04 08:33 CST, Phase 17b); the gpu parity
#: test re-checks them against ``/object_info``.
KNOWN_NODES: frozenset[str] = frozenset(
    {
        "CheckpointLoaderSimple",
        "CLIPSetLastLayer",
        "CLIPTextEncode",
        "CLIPVisionEncode",
        "CLIPVisionLoader",
        "ControlNetApplyAdvanced",
        "ControlNetLoader",
        "EmptyLatentImage",
        "FeatherMask",
        "GrowMask",
        "ImageBlur",
        "ImageCompositeMasked",
        "ImageInvert",
        "ImageScale",
        "ImageScaleBy",
        "ImageToMask",
        "ImageUpscaleWithModel",
        "InpaintModelConditioning",
        "KSampler",
        "KSamplerAdvanced",
        "LatentUpscale",
        "LatentUpscaleBy",
        "LoadImage",
        "LoadImageMask",
        "LoraLoader",
        "MaskToImage",
        "P11IPAdapterApply",
        "P11IPAdapterLoader",
        "PreviewImage",
        "RepeatLatentBatch",
        "SaveImage",
        "SetLatentNoiseMask",
        "SetUnionControlNetType",
        "UpscaleModelLoader",
        "VAEDecode",
        "VAEDecodeTiled",
        "VAEEncode",
        "VAEEncodeForInpaint",
        "VAEEncodeTiled",
        "VAELoader",
    }
)
OUTPUT_NODES = frozenset({"SaveImage", "PreviewImage"})
SAMPLERS = frozenset({"KSampler", "KSamplerAdvanced"})
MODEL_INPUTS = {
    "CheckpointLoaderSimple": "ckpt_name",
    "CLIPVisionLoader": "clip_name",
    "P11IPAdapterLoader": "ipadapter_file",
    "VAELoader": "vae_name",
    "LoraLoader": "lora_name",
    "UpscaleModelLoader": "model_name",
    "ControlNetLoader": "control_net_name",
}
#: Upscale factor of the fake's upscale models (4xNomosWebPhoto in the default set).
FAKE_UPSCALE = 4

Failure = Literal["oom", "validation", "crash", "execution"]


@dataclass
class FakeConfig:
    #: Seconds per sampler step and per other node (0 = as fast as possible).
    step_delay: float = 0.0
    node_delay: float = 0.0
    #: Largest sampler latent (in image pixels, width x height x batch) that fits per VRAM mode;
    #: anything larger raises ``EngineOOM`` like a real 8 GB card would.
    oom_pixels: Mapping[VramMode, int] = field(
        default_factory=lambda: {"dynamic": 2048 * 2048, "lowvram": 3072 * 3072}
    )
    #: Model file names the fake has; ``None`` accepts any name.
    models: Collection[str] | None = None
    max_restarts: int = 1
    restart_delay: float = 0.0
    run_timeout: float = 300.0
    version: str = "0.43.0"


class FakeEngine:
    def __init__(self, config: FakeConfig | None = None, vram_mode: VramMode = "dynamic") -> None:
        self.config = config or FakeConfig()
        self._vram_mode: VramMode = vram_mode
        self.state: EngineState = "stopped"
        self.restarts = 0
        self.last_error: str | None = None
        self.uploads: dict[str, bytes] = {}
        self.free_calls: list[bool] = []
        self.runs: list[dict[str, dict[str, Any]]] = []
        self.starts = 0
        self._failures: deque[tuple[Failure, str | None]] = deque()
        self._interrupt = asyncio.Event()
        self._running = False
        self._run_lock = asyncio.Lock()
        self._restart_task: asyncio.Task[None] | None = None

    # -- controls for tests ------------------------------------------------------------------

    def fail_next(self, kind: Failure, node: str | None = None, count: int = 1) -> None:
        """Make the next ``count`` runs fail with ``kind`` (``node`` defaults to the first)."""
        for _ in range(count):
            self._failures.append((kind, node))

    def crash(self) -> None:
        """Simulate the engine process dying while idle (the supervisor restarts it once)."""
        self._crashed("simulated crash")

    @property
    def vram_mode(self) -> VramMode:
        return self._vram_mode

    # -- lifecycle ---------------------------------------------------------------------------

    async def start(self) -> None:
        if self.state == "ready":
            return
        self.state = "ready"
        self.starts += 1
        self.restarts = 0

    async def stop(self) -> None:
        if self._restart_task:
            self._restart_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._restart_task
            self._restart_task = None
        self.state = "stopped"

    async def restart(self, vram_mode: VramMode | None = None) -> None:
        if vram_mode is not None:
            self._vram_mode = vram_mode
        self.state = "ready"
        self.starts += 1

    async def health(self) -> EngineHealth:
        return EngineHealth(
            state=self.state,
            vram_mode=self._vram_mode,
            port=None,
            pid=None,
            version=self.config.version if self.state == "ready" else None,
            restarts=self.restarts,
            last_error=self.last_error,
        )

    async def system_stats(self) -> SystemStats:
        self._require_ready()
        gib = 1024**3
        return SystemStats(
            version=self.config.version,
            python_version="3.12 (fake)",
            pytorch_version="fake",
            ram_total=32 * gib,
            ram_free=24 * gib,
            devices=(DeviceStats("Fake GPU", "cuda", 8 * gib, 7 * gib, 8 * gib, 7 * gib),),
        )

    def _require_ready(self) -> None:
        if self.state == "crashed":
            raise EngineCrashed(f"The engine stopped unexpectedly ({self.last_error}).")
        if self.state != "ready":
            raise EngineUnavailable(f"The engine is {self.state}. Start it first.")

    def _crashed(self, why: str) -> None:
        self.state = "crashed"
        self.last_error = why
        if self.restarts < self.config.max_restarts:
            self.restarts += 1
            self._restart_task = asyncio.get_event_loop().create_task(self._auto_restart())

    async def _auto_restart(self) -> None:
        await asyncio.sleep(self.config.restart_delay)
        self.state = "ready"
        self.starts += 1

    # -- requests ----------------------------------------------------------------------------

    async def upload(self, image: Path | bytes, kind: UploadKind = "image") -> EngineFileRef:
        self._require_ready()
        data = image.read_bytes() if isinstance(image, Path) else image
        name, _ = upload_name(data, kind)
        self.uploads[name] = data
        return EngineFileRef(name=name)

    async def interrupt(self) -> None:
        if self._running:
            self._interrupt.set()

    async def free_memory(self, unload_models: bool = True) -> None:
        self._require_ready()
        self.free_calls.append(unload_models)

    # -- run ---------------------------------------------------------------------------------

    async def run(
        self,
        graph: EngineGraph | Mapping[str, Any],
        *,
        on_event: EventCallback | None = None,
        timeout: float | None = None,
    ) -> RunResult:
        nodes = graph_nodes(graph)
        fallback_seed = graph.seed if isinstance(graph, EngineGraph) else 0
        async with self._run_lock:
            self._require_ready()
            order = self._validate(nodes)
            prompt_id = str(uuid.uuid4())
            self.runs.append(nodes)
            t0 = time.monotonic()
            self._interrupt.clear()
            self._running = True
            try:
                async with asyncio.timeout(timeout or self.config.run_timeout):
                    images, node_seconds = await self._execute(
                        nodes, order, prompt_id, on_event, fallback_seed
                    )
            except TimeoutError:
                raise EngineTimeout(
                    "The job took longer than its time limit and was stopped. "
                    "Try a faster preset or the Fast model."
                ) from None
            finally:
                self._running = False
        return RunResult(
            prompt_id=prompt_id,
            images=images,
            seconds=time.monotonic() - t0,
            node_seconds=node_seconds,
            vram_mode=self._vram_mode,
        )

    def _validate(self, nodes: Mapping[str, Mapping[str, Any]]) -> list[str]:
        if self._failures and self._failures[0][0] == "validation":
            _, target = self._failures.popleft()
            raise EngineValidation(target or next(iter(nodes), None), "simulated validation error")
        outputs = [k for k, v in nodes.items() if v["class_type"] in OUTPUT_NODES]
        if not outputs:
            raise EngineValidation(None, "Prompt has no outputs")
        for node_id, node in nodes.items():
            cls = node["class_type"]
            if cls not in KNOWN_NODES:
                raise EngineValidation(node_id, f"{cls}: node type not found")
            for name, value in node.get("inputs", {}).items():
                if _is_link(value) and str(value[0]) not in nodes:
                    raise EngineValidation(
                        node_id, f"{cls}: input {name!r} links to a missing node"
                    )
            if cls in ("LoadImage", "LoadImageMask"):
                image = str(node.get("inputs", {}).get("image", ""))
                if image not in self.uploads:
                    raise EngineValidation(node_id, f"{cls}: Invalid image file: {image}")
            field_name = MODEL_INPUTS.get(cls)
            if field_name and self.config.models is not None:
                value = node.get("inputs", {}).get(field_name)
                if value not in self.config.models:
                    raise EngineValidation(
                        node_id, f"{cls}: Value not in list: {field_name}: '{value}'"
                    )
        return _execution_order(nodes, outputs)

    async def _execute(
        self,
        nodes: Mapping[str, Mapping[str, Any]],
        order: list[str],
        prompt_id: str,
        on_event: EventCallback | None,
        fallback_seed: int,
    ) -> tuple[tuple[OutputImage, ...], dict[str, float]]:
        titles = node_titles(nodes)
        await emit(on_event, Queued(prompt_id))
        failure = self._failures.popleft() if self._failures else None
        images: list[OutputImage] = []
        node_seconds: dict[str, float] = {}
        for node_id in order:
            node = nodes[node_id]
            cls = node["class_type"]
            started = time.monotonic()
            await emit(on_event, Executing(node_id, titles.get(node_id)))
            self._check_interrupt()
            if failure and (failure[1] in (None, node_id)) and cls in SAMPLERS | OUTPUT_NODES:
                self._raise_failure(failure[0], node_id, cls)
            if cls in SAMPLERS:
                self._check_memory(nodes, node_id)
                steps = int(node["inputs"].get("steps", 20))
                for step in range(1, steps + 1):
                    await asyncio.sleep(self.config.step_delay)
                    self._check_interrupt()
                    await emit(on_event, Progress(step, steps, node_id, titles.get(node_id)))
            else:
                await asyncio.sleep(self.config.node_delay)
            if cls in OUTPUT_NODES:
                # One image per batch item, like ComfyUI's SaveImage.
                _, _, batch = _size(nodes, nodes[node_id]["inputs"].get("images"), self.uploads)
                outs = [
                    self._render(nodes, node_id, fallback_seed, len(images) + b, b)
                    for b in range(max(1, batch))
                ]
                images += outs
                ui = {"images": [{"filename": o.filename, "subfolder": "", "type": "output"}
                                 for o in outs]}  # fmt: skip
                await emit(on_event, Executed(node_id, ui))
            node_seconds[node_id] = time.monotonic() - started
        return tuple(images), node_seconds

    def _check_interrupt(self) -> None:
        if self._interrupt.is_set():
            self._interrupt.clear()
            raise EngineInterrupted("The job was cancelled.")

    def _raise_failure(self, kind: Failure, node_id: str, cls: str) -> None:
        if kind == "oom":
            raise EngineOOM(
                f"Out of GPU memory in node {node_id} ({cls}). "
                "Try a smaller preset or the low-memory mode."
            )
        if kind == "crash":
            self._crashed("simulated crash during a run")
            raise EngineCrashed("The engine stopped while running the job. P11 restarts it once.")
        raise EngineExecutionError(node_id, "RuntimeError", "simulated failure")

    def _check_memory(self, nodes: Mapping[str, Mapping[str, Any]], node_id: str) -> None:
        latent = nodes[node_id]["inputs"].get("latent_image")
        w, h, batch = _size(nodes, latent, self.uploads) if _is_link(latent) else (512, 512, 1)
        if w * h * batch > self.config.oom_pixels[self._vram_mode]:
            raise EngineOOM(
                f"Out of GPU memory in node {node_id} (KSampler) at {w}x{h}. "
                "Try a smaller preset or the low-memory mode."
            )

    def _render(
        self,
        nodes: Mapping[str, Mapping[str, Any]],
        node_id: str,
        fallback: int,
        index: int,
        batch_index: int = 0,
    ) -> OutputImage:
        node = nodes[node_id]
        w, h, _ = _size(nodes, node["inputs"].get("images"), self.uploads)
        seed = _upstream_seed(nodes, node_id)
        seed = fallback if seed is None else seed
        digest = hashlib.sha256(f"{seed}:{batch_index}".encode() if batch_index else
                                str(seed).encode()).digest()  # fmt: skip
        img = Image.new("RGB", (w, h), (digest[0], digest[1], digest[2]))
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, min(w, 260), min(h, 40)), fill=(0, 0, 0))
        draw.text((8, 8), f"P11 fake  seed {seed}  {w}x{h}", fill=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        prefix = str(node["inputs"].get("filename_prefix", "p11"))
        filename = f"{prefix.rsplit('/', 1)[-1]}_{index + 1:05d}_.png"
        return OutputImage(node=node_id, filename=filename, data=buf.getvalue())


# ---------------------------------------------------------------------------------------------
# Graph helpers.


def _is_link(value: Any) -> bool:
    return (
        isinstance(value, list | tuple)
        and len(value) == 2
        and isinstance(value[0], str | int)
        and isinstance(value[1], int)
    )


def _execution_order(nodes: Mapping[str, Mapping[str, Any]], outputs: list[str]) -> list[str]:
    """Dependencies first (depth-first post-order from the output nodes), like ComfyUI."""
    order: list[str] = []
    seen: set[str] = set()
    visiting: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in seen:
            return
        if node_id in visiting:
            raise EngineValidation(node_id, "the graph has a cycle")
        visiting.add(node_id)
        for value in nodes[node_id].get("inputs", {}).values():
            if _is_link(value):
                visit(str(value[0]))
        visiting.discard(node_id)
        seen.add(node_id)
        order.append(node_id)

    for out in sorted(outputs, key=_node_key):
        visit(out)
    return order


def _node_key(node_id: str) -> tuple[int, str]:
    return (int(node_id), "") if node_id.isdigit() else (1 << 30, node_id)


def _upstream_seed(nodes: Mapping[str, Mapping[str, Any]], node_id: str) -> int | None:
    seen: set[str] = set()
    stack = [node_id]
    best: int | None = None
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        node = nodes[nid]
        inputs = node.get("inputs", {})
        if node["class_type"] in SAMPLERS:
            seed = inputs.get("seed", inputs.get("noise_seed"))
            if isinstance(seed, int) and best is None:
                best = seed
        stack.extend(str(v[0]) for v in inputs.values() if _is_link(v))
    return best


def _size(
    nodes: Mapping[str, Mapping[str, Any]], link: Any, uploads: Mapping[str, bytes]
) -> tuple[int, int, int]:
    """(width, height, batch) of the IMAGE or LATENT (in pixels) a link carries."""
    if not _is_link(link):
        return 512, 512, 1
    node = nodes[str(link[0])]
    cls = node["class_type"]
    inp = node.get("inputs", {})

    def src(name: str) -> tuple[int, int, int]:
        return _size(nodes, inp.get(name), uploads)

    if cls == "EmptyLatentImage":
        return int(inp["width"]), int(inp["height"]), int(inp.get("batch_size", 1))
    if cls in ("LoadImage", "LoadImageMask"):
        data = uploads.get(str(inp.get("image")))
        if data is None:
            return 512, 512, 1
        with Image.open(io.BytesIO(data)) as img:
            return img.width, img.height, 1
    if cls in ("LatentUpscale", "ImageScale"):
        w0, h0, b = src("samples" if cls == "LatentUpscale" else "image")
        w, h = int(inp.get("width", 0)), int(inp.get("height", 0))
        if w == 0 and h == 0:
            return w0, h0, b
        if w == 0:
            w = round(w0 * h / h0)
        if h == 0:
            h = round(h0 * w / w0)
        return w, h, b
    if cls == "RepeatLatentBatch":
        w0, h0, b = src("samples")
        return w0, h0, b * int(inp.get("amount", 1))
    if cls in ("LatentUpscaleBy", "ImageScaleBy"):
        w0, h0, b = src("samples" if cls == "LatentUpscaleBy" else "image")
        f = float(inp.get("scale_by", 1.0))
        return round(w0 * f), round(h0 * f), b
    if cls == "ImageUpscaleWithModel":
        w0, h0, b = src("image")
        return w0 * FAKE_UPSCALE, h0 * FAKE_UPSCALE, b
    if cls in ("VAEDecode", "VAEDecodeTiled", "SetLatentNoiseMask"):
        return src("samples")
    if cls in ("VAEEncode", "VAEEncodeTiled", "VAEEncodeForInpaint", "InpaintModelConditioning"):
        return src("pixels")
    if cls in SAMPLERS:
        return src("latent_image")
    for value in inp.values():
        if _is_link(value):
            return _size(nodes, value, uploads)
    return 512, 512, 1

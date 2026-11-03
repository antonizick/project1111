"""Run one job: compile each step (Phase 04), feed it to the engine, save and index the outputs.

A job is a recipe + bindings, run ``count`` times (run ``i`` gets ``resolve_seed(strategy, i)``).
Each graph-producing step's output feeds the next step's ``p11:step:<i>`` input. Every output is
saved under the R7 layout with a sidecar and the recipe embedded in the PNG, then added to the
gallery index; step ``i``'s ``parent`` is step ``i-1``'s image, so an edit chain is navigable.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from p11 import __version__
from p11.engine.base import (
    Engine,
    EngineEvent,
    EngineInterrupted,
    Executing,
    Preview,
    Progress,
    Retrying,
    UploadKind,
)
from p11.engine.base import bind_inputs as bind_graph_inputs
from p11.engine.recovery import run_with_oom_retry
from p11.media import composite as composite_media
from p11.media.control import Controls
from p11.media.faces import FaceKit, run_face_restore, run_face_swap
from p11.media.imageio import open_rgb
from p11.media.inpaint import Prepared, check_mask, prepare, stitch
from p11.media.inputs import ID_RE, InputStore, UnknownInput
from p11.media.nsfw import check_target
from p11.media.segment import Segmenters, Segments
from p11.outputs import metadata
from p11.outputs.index import GalleryIndex, entry_from_record
from p11.outputs.layout import output_path
from p11.recipe.compile import EngineGraph, GraphInput, LocalStep, PlanItem, compile, resolve_seed
from p11.recipe.migrate import migrate
from p11.recipe.model import FileRef, Recipe
from p11.recipe.registry import ModelRegistry

log = logging.getLogger("p11.jobs")

Bindings = dict[str, str | FileRef]
BINDINGS = TypeAdapter(dict[str, str | FileRef])
GALLERY_PREFIX = "gallery/"
PREVIEW_INTERVAL = 0.5
RETRY_NOTE = "Out of GPU memory: retrying in low-memory mode."
Publish = Callable[[str, dict[str, Any]], object]


def parse_bindings(raw: Mapping[str, Any]) -> Bindings:
    """JSON bindings → ``str`` for text slots and ``FileRef`` for files (``{"ref": …}``)."""
    return BINDINGS.validate_python(dict(raw))


def gallery_ref(image_id: int) -> str:
    """The ``FileRef.ref`` that names a gallery image (for edits of an earlier output)."""
    return f"{GALLERY_PREFIX}{image_id}"


class JobControl:
    """Cancellation and the thermal pause for one running job."""

    def __init__(self, thermal: Callable[[JobControl], Awaitable[None]] | None = None) -> None:
        self.cancelled = False
        self._thermal = thermal

    def cancel(self) -> None:
        self.cancelled = True

    async def checkpoint(self, *, long: bool = False) -> None:
        """Between units of work: raise if cancelled; for long jobs wait while the GPU is hot."""
        if self.cancelled:
            raise EngineInterrupted("The job was cancelled.")
        if long and self._thermal is not None:
            await self._thermal(self)
            if self.cancelled:
                raise EngineInterrupted("The job was cancelled.")


@dataclass(frozen=True)
class Saved:
    path: Path
    output: metadata.StepOutput
    #: Relative path of the image this one was made from.
    parent: str | None


@dataclass
class RunReport:
    image_ids: list[int] = field(default_factory=list)
    retried: bool = False


@dataclass
class Runner:
    engine: Engine
    registry: Callable[[], ModelRegistry]
    outputs_root: Path
    gallery: GalleryIndex
    inputs: InputStore
    #: Subject segmentation for ``replace_background`` local steps (ADR-0026); the default
    #: resolves manifest IDs through the models root and raises a plain-English error when the
    #: model is missing.
    segmenters: Segments = field(default_factory=Segmenters)
    #: Face detection, swap, restore and the S5 NSFW guard (ADR-0028/0029).
    faces: FaceKit = field(default_factory=FaceKit)
    #: Control maps for ``pose`` steps (ADR-0030).
    controls: Controls = field(default_factory=Controls)
    run_timeout: float | None = None
    clock: Callable[[], datetime] = field(default=lambda: datetime.now().astimezone())

    def resolve_file(self, ref: FileRef) -> bytes:
        """Bytes of an upload (``img-…``) or of a gallery image (``gallery/<id>``)."""
        if ref.ref.startswith(GALLERY_PREFIX):
            tail = ref.ref.removeprefix(GALLERY_PREFIX)
            entry = self.gallery.get(int(tail)) if tail.isdigit() else None
            if entry is None:
                raise UnknownInput(f"Gallery image {tail!r} does not exist any more.")
            path = (self.outputs_root / entry.path).resolve()
            if not path.is_relative_to(self.outputs_root.resolve()) or not path.is_file():
                raise UnknownInput(f"The file of gallery image {tail} is gone.")
            return path.read_bytes()
        if not ID_RE.match(ref.ref):
            raise UnknownInput(f"{ref.ref!r} is not an upload or gallery image.")
        stored = self.inputs.get(ref.ref)
        if stored.kind == "video":
            raise UnknownInput(f"Upload {ref.ref!r} is a video, not an image.")
        return stored.path.read_bytes()

    def check_files(self, recipe: Recipe, bindings: Bindings) -> None:
        """Fail early (at submit time) if a bound or source file does not exist."""
        refs = [b for b in bindings.values() if isinstance(b, FileRef)]
        if recipe.source_image is not None:
            refs.append(recipe.source_image)
        for ref in refs:
            self.resolve_file(ref)

    def guard_targets(self, items: list[PlanItem], recipe: Recipe) -> None:
        """S5 (ADR-0029): refuse a face swap onto a sexual or nude target before it is queued.

        The swap itself checks again at run time, so a target that only exists after an earlier
        step runs is still covered. Nothing can turn this off.
        """
        for item in items:
            if not isinstance(item, LocalStep) or item.op != "face_swap":
                continue
            for inp in item.inputs:
                if inp.placeholder != "image" or inp.source == "step":
                    continue
                try:
                    data = self._input_bytes(inp, {}, recipe, {})
                except UnknownInput:
                    continue  # an image the run will make: checked again when it exists
                check_target(self.faces.guard(), open_rgb(data))

    def validate(self, recipe: Recipe, bindings: Bindings) -> list[PlanItem]:
        """Compile with a fixed seed: slot, model and step errors surface before queueing."""
        items = compile(recipe, bindings, self.registry(), seed=0)
        self.check_files(recipe, bindings)
        self.guard_targets(items, recipe)
        for item in items:
            if isinstance(item, LocalStep):
                masks = [i for i in item.inputs if i.kind == "mask"]
            else:
                masks = [
                    i
                    for i in item.inputs
                    if item.prep is not None and i.placeholder == item.prep.mask
                ]
            for inp in masks:
                if inp.data is not None:
                    check_mask(inp.data)
                elif inp.file is not None:
                    check_mask(self.resolve_file(inp.file))
        return items

    async def run(
        self,
        *,
        recipe: Recipe,
        bindings: Bindings,
        count: int,
        template: str | None,
        parent: str | None,
        control: JobControl,
        publish: Publish,
        job_id: str,
        on_progress: Callable[[float, str | None], None],
    ) -> RunReport:
        report = RunReport()
        registry = self.registry()
        rng = random.Random()
        slot_kinds = {s.name: s.kind for s in recipe.slots}
        health = await self.engine.health()
        previews = _Throttle(PREVIEW_INTERVAL)
        for run_index in range(count):
            seed = resolve_seed(recipe.seed, run_index, rng)
            graphs = compile(recipe, bindings, registry, seed=seed, run_index=run_index)
            total = count * len(graphs)
            long = total > 1
            images: dict[int, bytes] = {}
            saved: list[Saved] = []
            chain_parent = parent
            timings: dict[str, float] = {}
            now = self.clock()
            local_out: dict[str, bytes] = {}
            for gi, item in enumerate(graphs):
                await control.checkpoint(long=long)
                done = run_index * len(graphs) + gi

                where = _Where(job_id, run_index, count, gi, len(graphs), done, total)
                on_event = _event_handler(where, publish, on_progress, report, previews)
                last = gi == len(graphs) - 1
                # An item another item of the same step follows is intermediate: only the step's
                # last item is saved and becomes the next step's input (ADR-0027).
                intermediate = not last and graphs[gi + 1].step_index == item.step_index
                if isinstance(item, LocalStep):
                    data = {
                        inp.placeholder: self._input_bytes(inp, images, recipe, local_out)
                        for inp in item.inputs
                    }
                    t0 = time.perf_counter()
                    made = await asyncio.to_thread(self._run_local, item, data)
                    local_out.update({f"p11:local:{k}": v for k, v in made.items()})
                    images[item.step_index] = made["image"]
                    timings[f"step-{item.step_index:02d}-local"] = round(
                        time.perf_counter() - t0, 3
                    )
                    outs = [made["image"]]
                else:
                    nodes, prepared = await self._bind(item, images, recipe, slot_kinds, local_out)
                    result = await run_with_oom_retry(
                        self.engine, nodes, on_event=on_event, timeout=self.run_timeout
                    )
                    if result.retried:
                        report.retried = True
                    found = [i for i in result.images if i.node == item.output_node]
                    found = found or list(result.images)
                    if not found:
                        raise EngineInterrupted("The engine returned no image.")
                    if prepared is not None:
                        found = [replace(o, data=stitch(prepared, o.data)) for o in found]
                    images[item.step_index] = found[0].data
                    timings[f"step-{item.step_index:02d}"] = round(result.seconds, 3)
                    outs = [o.data for o in found]
                if intermediate:
                    outs = []
                first_rel: str | None = None
                for bi, out_data in enumerate(outs):
                    parts = [] if last else [f"{item.step_index:02d}-{item.step_type}"]
                    if len(outs) > 1:
                        parts.append(str(bi + 1))
                    path = output_path(
                        self.outputs_root, now, template, seed, "-".join(parts) or None
                    )
                    path.write_bytes(out_data)
                    size = _png_size(out_data)
                    rel = path.relative_to(self.outputs_root).as_posix()
                    first_rel = first_rel or rel
                    step_out = metadata.StepOutput(
                        step_index=item.step_index, step_type=item.step_type, path=rel,
                        width=size[0], height=size[1],
                    )  # fmt: skip
                    saved.append(Saved(path, step_out, chain_parent))
                # The next step was made from this step's first image.
                if first_rel is not None:
                    chain_parent = first_rel
                on_progress((done + 1) / total, None)
            report.image_ids += self._record(
                recipe=recipe,
                bindings=bindings,
                seed=seed,
                graphs=graphs,
                registry=registry,
                engine_version=health.version or "",
                saved=saved,
                timings=timings,
                template=template,
                job_id=job_id,
                publish=publish,
            )
        return report

    async def _bind(
        self,
        graph: EngineGraph,
        images: Mapping[int, bytes],
        recipe: Recipe,
        slot_kinds: Mapping[str, str],
        local_out: Mapping[str, bytes],
    ) -> tuple[EngineGraph | dict[str, Any], Prepared | None]:
        """Upload the graph's inputs (prepared by ``MaskPrep`` for inpaint) and bind them."""
        if not graph.inputs:
            return graph, None
        data = {
            inp.placeholder: self._input_bytes(inp, images, recipe, local_out)
            for inp in graph.inputs
        }
        prepared = None
        if graph.prep is not None:
            prep = graph.prep
            prepared = prepare(data[prep.image], data[prep.mask], prep)
            data[prep.image], data[prep.mask] = prepared.image, prepared.mask
        files = {}
        for inp in graph.inputs:
            mask = inp.kind == "mask" or bool(inp.slot and slot_kinds.get(inp.slot) == "mask")
            kind: UploadKind = "mask" if mask else "image"
            raw = data[inp.placeholder]
            if inp.transform:
                raw = await asyncio.to_thread(self.controls.transform, inp.transform, raw)
            files[inp.placeholder] = await self.engine.upload(raw, kind)
        return bind_graph_inputs(graph, files), prepared

    def _input_bytes(
        self,
        inp: GraphInput,
        images: Mapping[int, bytes],
        recipe: Recipe,
        local_out: Mapping[str, bytes],
    ) -> bytes:
        if inp.source == "step":
            assert inp.step is not None
            return images[inp.step]
        if inp.source == "inline":
            assert inp.data is not None
            return inp.data
        if inp.source == "local":
            try:
                return local_out[inp.placeholder]
            except KeyError:
                raise UnknownInput(
                    "This step needs the output of its own earlier part, which is missing."
                ) from None
        file = inp.file if inp.source == "slot" else recipe.source_image
        if file is None:
            raise UnknownInput("This step needs an input image, but none was given.")
        return self.resolve_file(file)

    def _run_local(self, item: LocalStep, data: Mapping[str, bytes]) -> dict[str, bytes]:
        """Run one local step in P11 (ADR-0027). Phase 14 adds ``text_overlay`` here."""
        if item.op == "replace_background":
            return composite_media.run_replace_background(item.params, data, self.segmenters)
        if item.op == "face_swap":
            # The S5 guard runs inside: before the swap and again on the result (ADR-0029).
            return run_face_swap(item.params, data, self.faces)
        if item.op == "face_restore":
            return run_face_restore(item.params, data, self.faces)
        raise ValueError(f"Unknown local step {item.op!r}.")

    def _record(
        self,
        *,
        recipe: Recipe,
        bindings: Bindings,
        seed: int,
        graphs: list[PlanItem],
        registry: ModelRegistry,
        engine_version: str,
        saved: list[Saved],
        timings: dict[str, float],
        template: str | None,
        job_id: str,
        publish: Publish,
    ) -> list[int]:
        model_hashes: dict[str, str | None] = {}
        for g in graphs:
            for m in g.models:
                model_hashes[m] = registry.get(m).sha256
        timings["total"] = round(sum(timings.values()), 3)
        base = metadata.RunRecord(
            recipe=recipe,
            bindings=dict(bindings),
            seed=seed,
            model_hashes=model_hashes,
            engine_version=engine_version,
            p11_version=__version__,
            timings=timings,
            step_outputs=tuple(s.output for s in saved),
            template=template,
        )
        ids = []
        for item in saved:
            record = base.model_copy(update={"parent": item.parent})
            metadata.write_sidecar(item.path, record)
            metadata.embed_record(item.path, record)
            entry = entry_from_record(item.output.path, record)
            parent_entry = self.gallery.by_path(item.parent) if item.parent else None
            if parent_entry is not None:
                entry = replace(entry, parent_id=parent_entry.id)
            image_id = self.gallery.add(entry)
            ids.append(image_id)
            stored = self.gallery.get(image_id)
            publish("image", {"job": job_id, "image": image_json(stored) if stored else None})
            log.info("saved output", extra={"job": job_id, "image": image_id})
        return ids


@dataclass(frozen=True)
class _Where:
    job: str
    run: int
    runs: int
    graph: int
    graphs: int
    done: int
    total: int

    def fields(self, progress: float) -> dict[str, Any]:
        return {"job": self.job, "run": self.run, "runs": self.runs, "graph": self.graph,
                "graphs": self.graphs, "progress": round(progress, 4)}  # fmt: skip


class _Throttle:
    def __init__(self, interval: float) -> None:
        self.interval = interval
        self.last = -interval

    def ready(self) -> bool:
        now = time.monotonic()
        if now - self.last < self.interval:
            return False
        self.last = now
        return True


def _event_handler(
    where: _Where,
    publish: Publish,
    on_progress: Callable[[float, str | None], None],
    report: RunReport,
    previews: _Throttle,
) -> Callable[[EngineEvent], None]:
    """Engine events of one graph → job progress, SSE ``progress``/``preview`` events."""

    def on_event(ev: EngineEvent) -> None:
        if isinstance(ev, Progress) and ev.total:
            frac = (where.done + ev.step / ev.total) / where.total
            on_progress(frac, None)
            publish(
                "progress",
                {**where.fields(frac), "step": ev.step, "total": ev.total, "title": ev.title},
            )
        elif isinstance(ev, Executing):
            publish("progress", {**where.fields(where.done / where.total), "title": ev.title})
        elif isinstance(ev, Preview) and previews.ready():
            data = base64.b64encode(ev.data).decode()
            publish("preview", {"job": where.job, "mime": ev.mime, "data": data})
        elif isinstance(ev, Retrying):
            report.retried = True
            on_progress(where.done / where.total, RETRY_NOTE)

    return on_event


def _png_size(data: bytes) -> tuple[int | None, int | None]:
    if data[:8] == metadata.PNG_SIGNATURE and data[12:16] == b"IHDR":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None, None


def image_json(entry: Any) -> dict[str, Any]:
    """A gallery entry as the API shows it."""
    return {
        "id": entry.id,
        "path": entry.path,
        "created_at": entry.created_at,
        "recipe_id": entry.recipe_id,
        "template": entry.template,
        "seed": entry.seed,
        "model": entry.model,
        "width": entry.width,
        "height": entry.height,
        "favourite": entry.favourite,
        "parent_id": entry.parent_id,
        "prompt": entry.prompt,
        "url": f"/api/images/{entry.id}",
        "thumb": f"/api/images/{entry.id}/thumb",
    }


def load_recipe(raw: Mapping[str, Any]) -> Recipe:
    return migrate(raw)

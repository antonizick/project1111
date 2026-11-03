"""Run one job: compile each step (Phase 04), feed it to the engine, save and index the outputs.

A job is a recipe + bindings, run ``count`` times (run ``i`` gets ``resolve_seed(strategy, i)``).
Each graph-producing step's output feeds the next step's ``p11:step:<i>`` input. Every output is
saved under the R7 layout with a sidecar and the recipe embedded in the PNG, then added to the
gallery index; step ``i``'s ``parent`` is step ``i-1``'s image, so an edit chain is navigable.
"""

from __future__ import annotations

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
from p11.media.inpaint import Prepared, check_mask, prepare, stitch
from p11.media.inputs import ID_RE, InputStore, UnknownInput
from p11.outputs import metadata
from p11.outputs.index import GalleryIndex, entry_from_record
from p11.outputs.layout import output_path
from p11.recipe.compile import EngineGraph, GraphInput, compile, resolve_seed
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

    def validate(self, recipe: Recipe, bindings: Bindings) -> list[EngineGraph]:
        """Compile with a fixed seed: slot, model and step errors surface before queueing."""
        graphs = compile(recipe, bindings, self.registry(), seed=0)
        self.check_files(recipe, bindings)
        for graph in graphs:
            for inp in graph.inputs:
                if graph.prep is None or inp.placeholder != graph.prep.mask:
                    continue
                if inp.data is not None:
                    check_mask(inp.data)
                elif inp.file is not None:
                    check_mask(self.resolve_file(inp.file))
        return graphs

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
            for gi, graph in enumerate(graphs):
                await control.checkpoint(long=long)
                done = run_index * len(graphs) + gi

                where = _Where(job_id, run_index, count, gi, len(graphs), done, total)
                on_event = _event_handler(where, publish, on_progress, report, previews)
                nodes, prepared = await self._bind(graph, images, recipe, slot_kinds)
                result = await run_with_oom_retry(
                    self.engine, nodes, on_event=on_event, timeout=self.run_timeout
                )
                if result.retried:
                    report.retried = True
                outs = [i for i in result.images if i.node == graph.output_node]
                outs = outs or list(result.images)
                if not outs:
                    raise EngineInterrupted("The engine returned no image.")
                if prepared is not None:
                    outs = [replace(o, data=stitch(prepared, o.data)) for o in outs]
                images[graph.step_index] = outs[0].data
                last = gi == len(graphs) - 1
                first_rel: str | None = None
                for bi, out in enumerate(outs):
                    parts = [] if last else [f"{graph.step_index:02d}-{graph.step_type}"]
                    if len(outs) > 1:
                        parts.append(str(bi + 1))
                    path = output_path(
                        self.outputs_root, now, template, seed, "-".join(parts) or None
                    )
                    path.write_bytes(out.data)
                    size = _png_size(out.data)
                    rel = path.relative_to(self.outputs_root).as_posix()
                    first_rel = first_rel or rel
                    step_out = metadata.StepOutput(
                        step_index=graph.step_index, step_type=graph.step_type, path=rel,
                        width=size[0], height=size[1],
                    )  # fmt: skip
                    saved.append(Saved(path, step_out, chain_parent))
                # The next step was made from this step's first image.
                chain_parent = first_rel
                timings[f"step-{graph.step_index:02d}"] = round(result.seconds, 3)
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
    ) -> tuple[EngineGraph | dict[str, Any], Prepared | None]:
        """Upload the graph's inputs (prepared by ``MaskPrep`` for inpaint) and bind them."""
        if not graph.inputs:
            return graph, None
        data = {inp.placeholder: self._input_bytes(inp, images, recipe) for inp in graph.inputs}
        prepared = None
        if graph.prep is not None:
            prep = graph.prep
            prepared = prepare(data[prep.image], data[prep.mask], prep)
            data[prep.image], data[prep.mask] = prepared.image, prepared.mask
        files = {}
        for inp in graph.inputs:
            mask = inp.kind == "mask" or bool(inp.slot and slot_kinds.get(inp.slot) == "mask")
            kind: UploadKind = "mask" if mask else "image"
            files[inp.placeholder] = await self.engine.upload(data[inp.placeholder], kind)
        return bind_graph_inputs(graph, files), prepared

    def _input_bytes(self, inp: GraphInput, images: Mapping[int, bytes], recipe: Recipe) -> bytes:
        if inp.source == "step":
            assert inp.step is not None
            return images[inp.step]
        if inp.source == "inline":
            assert inp.data is not None
            return inp.data
        file = inp.file if inp.source == "slot" else recipe.source_image
        if file is None:
            raise UnknownInput("This step needs an input image, but none was given.")
        return self.resolve_file(file)

    def _record(
        self,
        *,
        recipe: Recipe,
        bindings: Bindings,
        seed: int,
        graphs: list[EngineGraph],
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

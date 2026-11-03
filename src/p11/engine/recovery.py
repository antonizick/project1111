"""OOM recovery (spec R5, ADR-0018): free memory, retry once in low-VRAM mode, then explain."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from p11.engine.base import (
    Engine,
    EngineOOM,
    EventCallback,
    Retrying,
    RunResult,
    emit,
)
from p11.recipe.compile import EngineGraph

OOM_MESSAGE = (
    "Out of GPU memory: P11 retried in low-memory mode and it still did not fit. "
    "Try a smaller preset, the Fast model, or close other programs that use the GPU."
)


async def run_with_oom_retry(
    engine: Engine,
    graph: EngineGraph | Mapping[str, Any],
    *,
    on_event: EventCallback | None = None,
    timeout: float | None = None,
) -> RunResult:
    """Run ``graph``; on ``EngineOOM`` unload models and retry once with ``lowvram``.

    The engine stays in low-VRAM mode afterwards (ADR-0020): restarting back costs a model load,
    and a job that needed it is likely to be followed by a similar one. The caller (the job
    queue, Phase 07) may ``restart("dynamic")`` when it is idle.
    """
    try:
        return await engine.run(graph, on_event=on_event, timeout=timeout)
    except EngineOOM as first:
        await emit(on_event, Retrying(str(first), "lowvram"))
        try:
            await engine.free_memory(unload_models=True)
            if engine.vram_mode != "lowvram":
                await engine.restart("lowvram")
            result = await engine.run(graph, on_event=on_event, timeout=timeout)
        except EngineOOM as second:
            raise EngineOOM(OOM_MESSAGE) from second
        return replace(result, retried=True)

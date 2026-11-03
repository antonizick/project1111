"""Summarize bench runs into Markdown tables and build the contact sheet (not committed).

    uv run python -m scripts.bench.report            # tables to stdout, sheet to ~/.cache/p11/bench/
"""

from __future__ import annotations

import html
import json
import statistics
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw

from . import prompts
from .configs import MODELS
from .engine import BENCH
from .schema import BenchResult

RUNS = BENCH / "runs"


def load(stage: str) -> list[BenchResult]:
    return [BenchResult.model_validate_json(p.read_text()) for p in sorted((RUNS / stage).glob("*.json"))]


def fmt(x: float | None, nd: int = 1) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def base_table(rs: list[BenchResult]) -> str:
    rows = ["| Model | Sampler | Steps | CFG | Cold s | Warm s (median) | it/s | Peak VRAM MiB (engine) | Peak RAM MiB | Errors |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    groups: dict[tuple[str, str, int], list[BenchResult]] = defaultdict(list)
    for r in rs:
        groups[(r.model, r.sampler, r.steps)].append(r)
    for (model, sampler, steps), g in groups.items():
        cold = [r.seconds for r in g if r.cold and r.seconds]
        warm = [r.seconds for r in g if not r.cold and r.seconds]
        its = [r.it_per_s for r in g if r.it_per_s]
        rows.append(
            f"| {model} | {sampler} | {steps} | {g[0].cfg:g} | {fmt(cold[0] if cold else None)} | "
            f"{fmt(statistics.median(warm) if warm else None)} | {fmt(statistics.median(its) if its else None, 2)} | "
            f"{max((r.peak_vram_mib or 0) for r in g)} ({max((r.peak_vram_engine_mib or 0) for r in g)}) | "
            f"{max((r.peak_ram_mib or 0) for r in g)} | {sum(1 for r in g if r.error)} |")
    return "\n".join(rows)


def preset_table(rs: list[BenchResult]) -> str:
    rows = ["| Model | VRAM mode | Preset | Chain | Seconds | Peak VRAM MiB (engine) | Result |",
            "|---|---|---|---|---:|---:|---|"]
    for r in sorted(rs, key=lambda r: (r.model, r.vram_mode, r.preset, r.chain, r.cold)):
        res = "OOM" if r.oom else ("error: " + r.error[:60] if r.error else "ok")
        rows.append(f"| {r.model} | {r.vram_mode} | {r.preset} | {r.chain}{' (cold)' if r.cold else ''} | "
                    f"{fmt(r.seconds)} | {r.peak_vram_mib or 'n/a'} ({r.peak_vram_engine_mib or 'n/a'}) | {res} |")
    return "\n".join(rows)


def contact_sheet(rs: list[BenchResult], name: str = "contact-sheet", portrait: bool = False) -> Path:
    default = {m.key: m.samplers[0].steps for m in MODELS.values()}
    cells = {(r.model, r.prompt_id): r for r in rs
             if r.output_path and (portrait or r.steps == default.get(r.model))}
    models = [m for m in MODELS if any(k[0] == m for k in cells)]
    pids = [p for p in prompts.ALL if any(k[1] == p for k in cells)]
    tw, th, lab = (232, 296, 18) if portrait else (336, 192, 18)
    sheet = Image.new("RGB", (140 + tw * len(models), lab + (th + 4) * len(pids)), "white")
    d = ImageDraw.Draw(sheet)
    for j, m in enumerate(models):
        d.text((140 + j * tw + 4, 2), m, fill="black")
    for i, pid in enumerate(pids):
        y = lab + i * (th + 4)
        d.text((4, y + th // 2), pid, fill="black")
        for j, m in enumerate(models):
            r = cells.get((m, pid))
            if r and r.output_path and Path(r.output_path).exists():
                im = Image.open(r.output_path).convert("RGB")
                im.thumbnail((tw - 4, th))
                sheet.paste(im, (140 + j * tw, y))
    png = BENCH / f"{name}.png"
    sheet.save(png)
    rows = []
    for pid in pids:
        tds = "".join(
            f'<td><a href="file://{html.escape(c.output_path)}"><img src="file://{html.escape(c.output_path)}" '
            f'width="320"></a><br><small>{fmt(c.seconds)} s</small></td>'
            if (c := cells.get((m, pid))) and c.output_path else "<td>-</td>"
            for m in models)
        rows.append(f"<tr><th title='{html.escape(prompts.ALL[pid])}'>{pid}</th>{tds}</tr>")
    head = "".join(f"<th>{m}</th>" for m in models)
    (BENCH / f"{name}.html").write_text(
        f"<!doctype html><meta charset=utf-8><title>P11 bake-off contact sheet</title>"
        f"<h1>P11 Phase 03 contact sheet (native 16:9 bucket, default sampler, seed {prompts.SEEDS[0]})</h1>"
        f"<table border=1><tr><th></th>{head}</tr>{''.join(rows)}</table>")
    return png


def main() -> None:
    base = load("base")
    print("## Base (native bucket)\n" + base_table(base))
    if (RUNS / "avatar").exists():
        print("\n## Avatar (portrait bucket)\n" + base_table(load("avatar")))
    for st in ("presets", "vram"):
        if (RUNS / st).exists():
            print(f"\n## {st}\n" + preset_table(load(st)))
    for p in sorted(RUNS.glob("stability-summary-*.json")):
        s = json.loads(p.read_text())
        secs = [x for x in s["seconds"] if x]
        print(f"\n## stability {s['model']} {s['preset']} {s['chain']} {s['mode']}: {s['n']} runs, "
              f"{s['failures']} failures, {s['ooms']} OOM, median {fmt(statistics.median(secs))} s, "
              f"max VRAM {max(v for v in s['peak_vram'] if v)} MiB")
    if base:
        print(f"\ncontact sheet: {contact_sheet(base)}")
    if (RUNS / "avatar").exists():
        print(f"avatar sheet: {contact_sheet(load('avatar'), 'avatar-sheet', portrait=True)}")


if __name__ == "__main__":
    main()

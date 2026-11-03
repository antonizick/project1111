"""``p11`` command line."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import typer
import uvicorn

from p11 import __version__, paths
from p11.config import load_settings
from p11.models.cli import app as models_app

app = typer.Typer(help="P11 Studio: local image generation.", no_args_is_help=True)
app.add_typer(models_app, name="models")

JSON_OPT = typer.Option(False, "--json", help="Print the result as JSON.")
EXIT_NOT_RUNNING = 3
log = logging.getLogger("p11.cli")


@app.command()
def version() -> None:
    """Print the P11 version."""
    typer.echo(__version__)


@app.command("paths")
def show_paths() -> None:
    """Print the resolved config, data, cache and output paths."""
    for name, value in vars(paths.resolve()).items():
        typer.echo(f"{name:9} {value}")


def _fail(message: str, hint: str = "", code: int = 1) -> None:
    typer.echo(f"Error: {message}", err=True)
    if hint:
        typer.echo(f"Hint: {hint}", err=True)
    raise typer.Exit(code)


@app.command()
def serve(
    fake: bool = typer.Option(False, "--fake", help="Use the FakeEngine (no GPU, no ComfyUI)."),
    port: int | None = typer.Option(None, "--port", min=1024, max=65535, help="Studio port."),
    debug: bool = typer.Option(False, "--debug", help="Verbose log (still redacts the token)."),
    demo: bool = typer.Option(True, "--demo/--no-demo", help="With --fake: seed a demo gallery."),
) -> None:
    """Run P11 Studio in the foreground on 127.0.0.1."""
    from p11 import lifecycle, logs
    from p11.api.app import create_app
    from p11.api.security import Session
    from p11.api.studio import StudioPaths
    from p11.engine import create_engine
    from p11.engine.base import Engine
    from p11.engine.process import port_in_use

    settings = load_settings()
    port = port or settings.studio_port
    log_file = logs.setup_logging(debug=debug)
    if lifecycle.running() is not None or port_in_use(settings.host, port):
        _fail(f"Port {port} is already in use.", "Is P11 already running? Try `p11 status`.")
    engine: Engine
    studio_paths = None
    if fake:
        from p11.engine.fake import FakeConfig, FakeEngine

        # A little delay per step so the UI phases see real progress events.
        engine = FakeEngine(FakeConfig(step_delay=0.05, node_delay=0.01))
        studio_paths = StudioPaths.sandbox(paths.cache_dir() / "fake")
    else:
        engine = create_engine(settings)
    session = Session()
    application = create_app(
        engine=engine,
        settings=settings,
        session=session,
        port=port,
        fake=fake,
        studio_paths=studio_paths,
        seed_demo=fake and demo,
    )
    pid = os.getpid()
    session.write()
    lifecycle.write_state(
        lifecycle.StudioState(pid=pid, port=port, fake=fake, started=_now(), log=str(log_file))
    )
    mode = " (fake engine)" if fake else ""
    typer.echo(f"P11 Studio{mode} on http://127.0.0.1:{port}. Open it with `p11 open`.")
    typer.echo(f"Log: {log_file}")
    try:
        uvicorn.run(
            application,
            host=settings.host,
            port=port,
            log_config=None,
            access_log=False,
            server_header=False,
            timeout_graceful_shutdown=10,
        )
    finally:
        lifecycle.clear_state(pid)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S %Z")


@app.command()
def start(
    fake: bool = typer.Option(False, "--fake", help="Use the FakeEngine (no GPU, no ComfyUI)."),
    port: int | None = typer.Option(None, "--port", min=1024, max=65535, help="Studio port."),
    debug: bool = typer.Option(False, "--debug", help="Verbose log (still redacts the token)."),
) -> None:
    """Start P11 Studio in the background."""
    from p11 import lifecycle

    already = lifecycle.running()
    if already is not None:
        typer.echo(f"P11 Studio is already running at {already.url} (pid {already.pid}).")
        return
    try:
        state = lifecycle.start_background(fake=fake, port=port, debug=debug)
    except lifecycle.StudioError as exc:
        _fail(str(exc), exc.hint)
        return
    mode = " with the fake engine" if state.fake else ""
    typer.echo(f"P11 Studio started{mode} at {state.url} (pid {state.pid}).")
    typer.echo("Open it with `p11 open`.")


@app.command()
def stop() -> None:
    """Stop the background P11 Studio (and the engine it started)."""
    from p11 import lifecycle

    state = lifecycle.stop()
    if state is None:
        typer.echo("P11 Studio is not running.")
        return
    typer.echo(f"P11 Studio stopped (pid {state.pid}).")


@app.command()
def status(
    as_json: bool = JSON_OPT,
    token_file: bool = typer.Option(
        False, "--token-file", help="Print where the session token is (for scripts)."
    ),
) -> None:
    """Show whether the Studio, engine and GPU are up, and what is queued."""
    from p11 import lifecycle
    from p11.api.security import token_path

    if token_file:
        typer.echo(token_path())
        return
    state = lifecycle.running()
    if state is None:
        if as_json:
            typer.echo(json.dumps({"running": False}))
        else:
            typer.echo("P11 Studio is not running. Start it with `p11 start`.")
        raise typer.Exit(EXIT_NOT_RUNNING)
    try:
        r = lifecycle.api(state, "GET", "/api/system")
        system: dict[str, Any] = r.json() if r.status_code == 200 else {}
    except (lifecycle.StudioError, OSError, ValueError):
        system = {}
    if as_json:
        typer.echo(json.dumps({"running": True, "pid": state.pid, "url": state.url, **system}))
        return
    mode = " (fake engine)" if state.fake else ""
    typer.echo(f"Studio  running{mode} at {state.url}, pid {state.pid}, since {state.started}")
    if not system:
        typer.echo("        (the API did not answer; see `p11 doctor`)")
        return
    eng = system["engine"]
    detail = f"{eng['state']}, {eng['vram_mode']} VRAM mode"
    if eng.get("version"):
        detail += f", ComfyUI {eng['version']}"
    if eng.get("restarts"):
        detail += f", {eng['restarts']} restart(s)"
    typer.echo(f"Engine  {detail} (starts on the first job, stops when idle)")
    gpu = system.get("gpu")
    if gpu:
        typer.echo(
            f"GPU     {gpu['temp_c']} °C, VRAM {gpu['vram_used_mib']}/{gpu['vram_total_mib']} MiB"
            + (f", {gpu['power_w']:.0f} W" if gpu.get("power_w") is not None else "")
        )
    q = system["queue"]
    typer.echo(f"Queue   {'1 running' if q['current'] else 'idle'}, {q['waiting']} waiting")


@app.command("open")
def open_ui(
    print_url: bool = typer.Option(
        False, "--print-url", help="Print the one-time URL instead of opening a browser."
    ),
) -> None:
    """Open P11 Studio in an app window (starts the Studio if needed)."""
    from p11 import lifecycle

    try:
        state = lifecycle.running()
        if state is None:
            typer.echo("Starting P11 Studio…")
            state = lifecycle.start_background()
        url = lifecycle.launch_url(state)
        if print_url:
            typer.echo(url)
            return
        lifecycle.open_browser(url)
    except lifecycle.StudioError as exc:
        _fail(str(exc), exc.hint)
        return
    typer.echo(f"Opened P11 Studio ({state.url}).")


@app.command()
def doctor(
    as_json: bool = JSON_OPT,
    quick: bool = typer.Option(False, "--quick", help="Skip the slow PyTorch/CUDA check."),
) -> None:
    """Check the GPU, engine, models, ports, disk space and permissions."""
    from p11.doctor import run_checks

    report = run_checks(quick=quick)
    if as_json:
        typer.echo(json.dumps(report.as_json(), indent=2))
    else:
        for c in report.checks:
            typer.echo(f"  ok    {c.name}: {c.detail}")
        for p in report.problems:
            mark = "ERROR" if p.severity == "error" else "warn "
            typer.echo(f"  {mark} {p.message}")
            if p.hint:
                typer.echo(f"        → {p.hint}")
        if not report.problems:
            typer.echo("All good.")
        elif report.ok:
            typer.echo("Ready, with warnings.")
    if not report.ok:
        raise typer.Exit(1)


@app.command()
def update() -> None:
    """Not implemented yet (Phase 15)."""
    typer.echo("p11 update: not implemented yet (Phase 15).")

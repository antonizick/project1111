"""``p11`` command line."""

from __future__ import annotations

import typer
import uvicorn

from p11 import __version__, paths
from p11.config import load_settings

app = typer.Typer(help="P11 Studio: local image generation.", no_args_is_help=True)


@app.command()
def version() -> None:
    """Print the P11 version."""
    typer.echo(__version__)


@app.command("paths")
def show_paths() -> None:
    """Print the resolved config, data, cache and output paths."""
    for name, value in vars(paths.resolve()).items():
        typer.echo(f"{name:9} {value}")


@app.command()
def serve() -> None:
    """Run P11 Studio in the foreground on 127.0.0.1."""
    from p11.api.app import create_app

    settings = load_settings()
    uvicorn.run(create_app(), host=settings.host, port=settings.studio_port)


def _stub(name: str, phase: str) -> None:
    def command() -> None:
        typer.echo(f"p11 {name}: not implemented yet (Phase {phase}).")

    command.__doc__ = f"Not implemented yet (Phase {phase})."
    app.command(name)(command)


for _name, _phase in [
    ("start", "07"),
    ("stop", "07"),
    ("status", "07"),
    ("open", "07"),
    ("doctor", "07"),
    ("models", "06"),
    ("update", "15"),
]:
    _stub(_name, _phase)

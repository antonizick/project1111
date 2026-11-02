from typer.testing import CliRunner

from p11 import __version__
from p11.cli import app

runner = CliRunner()


def test_version():
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0
    assert r.stdout.strip() == __version__


def test_paths(tmp_path):
    r = runner.invoke(app, ["paths"])
    assert r.exit_code == 0
    assert str(tmp_path / "config") in r.stdout


def test_stub():
    r = runner.invoke(app, ["doctor"])
    assert r.exit_code == 0
    assert "not implemented yet" in r.stdout

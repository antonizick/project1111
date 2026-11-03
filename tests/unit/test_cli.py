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


def test_serve_fake_uses_fake_engine(monkeypatch):
    from p11.engine.fake import FakeEngine

    seen = {}
    monkeypatch.setattr("p11.cli.uvicorn.run", lambda app, **kw: seen.update(app=app, **kw))
    result = runner.invoke(app, ["serve", "--fake"])
    assert result.exit_code == 0, result.output
    assert isinstance(seen["app"].state.engine, FakeEngine)
    assert seen["host"] == "127.0.0.1"
    runner.invoke(app, ["serve"])
    assert seen["app"].state.engine is None

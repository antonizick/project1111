import pytest
from pydantic import ValidationError

from p11.config import Settings, load_settings


def test_defaults():
    s = load_settings()
    assert s.host == "127.0.0.1"
    assert s.studio_port == 8111


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "::"])
def test_rejects_non_loopback(host):
    with pytest.raises(ValidationError):
        Settings(host=host)


def test_toml_and_env(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "config.toml").write_text("studio_port = 9000\nengine_port = 9001\n")
    monkeypatch.setenv("P11_ENGINE_PORT", "9002")
    s = load_settings()
    assert s.studio_port == 9000
    assert s.engine_port == 9002


def test_toml_cannot_unlock_host(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "config.toml").write_text('host = "0.0.0.0"\n')
    with pytest.raises(ValidationError):
        load_settings()

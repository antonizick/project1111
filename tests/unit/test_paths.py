import stat

from p11 import paths


def test_env_overrides(tmp_path):
    p = paths.resolve()
    assert p.config == tmp_path / "config"
    assert p.models == tmp_path / "data" / "models"
    assert p.gpu_lock == tmp_path / "cache" / "gpu.lock"


def test_xdg_defaults(monkeypatch, tmp_path):
    for v in ("P11_CONFIG_DIR", "P11_DATA_DIR", "P11_CACHE_DIR", "P11_PICTURES_DIR"):
        monkeypatch.delenv(v)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "x"))
    assert paths.data_dir() == tmp_path / "x" / "p11"


def test_ensure_private_dir_is_0700(tmp_path):
    d = paths.ensure_private_dir(tmp_path / "a" / "b")
    assert stat.S_IMODE(d.stat().st_mode) == 0o700

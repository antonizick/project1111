import shutil

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if shutil.which("nvidia-smi"):
        return
    skip = pytest.mark.skip(reason="no NVIDIA GPU present")
    for item in items:
        if "gpu" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    for var, sub in [
        ("P11_CONFIG_DIR", "config"),
        ("P11_DATA_DIR", "data"),
        ("P11_CACHE_DIR", "cache"),
        ("P11_PICTURES_DIR", "pictures"),
    ]:
        monkeypatch.setenv(var, str(tmp_path / sub))

"""P11's own IP-Adapter node pack (Phase 12, ADR-0031): the parts that do not need torch.

The pack lives in ``engine/custom_nodes/`` and runs inside the engine's venv, but its pure helpers
(key nesting, the schedule gate) are worth testing from P11's own suite. The full path (projection +
attention patch) is exercised on the GPU by the acceptance run.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PACK = (
    Path(__file__).resolve().parents[2]
    / "engine"
    / "custom_nodes"
    / "p11_ipadapter"
    / "__init__.py"
)


def load_pack():
    spec = importlib.util.spec_from_file_location("p11_ipadapter_pack", PACK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_pack_registers_exactly_the_two_nodes() -> None:
    pack = load_pack()
    assert set(pack.NODE_CLASS_MAPPINGS) == {"P11IPAdapterLoader", "P11IPAdapterApply"}
    assert set(pack.NODE_DISPLAY_NAME_MAPPINGS) == set(pack.NODE_CLASS_MAPPINGS)
    for name, cls in pack.NODE_CLASS_MAPPINGS.items():
        assert hasattr(cls, "INPUT_TYPES"), name
        assert cls.RETURN_TYPES


def test_key_groups_nest_and_flatten_back() -> None:
    pack = load_pack()
    flat = {"a.b.c": 1, "a.b.d": 2, "a.e": 3, "top": 4}
    nested = pack._nest(flat)
    assert nested == {"a": {"b": {"c": 1, "d": 2}, "e": 3}, "top": 4}
    assert pack._flatten(nested["a"]) == {"b.c": 1, "b.d": 2, "e": 3}
    assert pack._flatten(nested["a"], "a.") == {"a.b.c": 1, "a.b.d": 2, "a.e": 3}


def test_the_schedule_gate_holds_the_reference_out_of_the_edges() -> None:
    pack = load_pack()
    state = {"sigma_max": None}
    gate = pack._gate

    class Sigma:
        def __init__(self, value: float) -> None:
            self.value = value

        def reshape(self, *_: object) -> object:
            return self

        def __getitem__(self, _: object) -> float:
            return self.value

    # The first call sets sigma_max and defines the progress scale.
    assert gate(state, {"sigmas": Sigma(1.0)}, 0.7, 0.0, 1.0) == 0.7
    assert gate(state, {"sigmas": Sigma(0.5)}, 0.7, 0.0, 1.0) == 0.7
    assert gate(state, {"sigmas": Sigma(0.0)}, 0.7, 0.2, 0.8) == 0.0  # progress 1.0 > end
    assert gate(state, {"sigmas": Sigma(1.0)}, 0.7, 0.2, 0.8) == 0.0  # progress 0.0 < start
    # No sigma (a non-sampling pass) keeps the weight as given.
    assert gate(state, {}, 0.7, 0.2, 0.8) == 0.7
    assert gate(state, {"sigmas": Sigma(0.5)}, 0.0, 0.0, 1.0) == 0.0


def test_the_pack_refuses_a_bad_window() -> None:
    pack = load_pack()
    node = pack.P11IPAdapterApply()
    with pytest.raises(pack.P11IPAdapterError, match="End must not be before"):
        node.apply(object(), object(), object(), 0.5, 0.8, 0.2)


def test_the_pack_is_the_only_one_the_engine_loads() -> None:
    """S3: the launch flags whitelist exactly P11's own pack (ADR-0031)."""
    import tomllib

    lock = tomllib.loads((PACK.parents[3] / "engine" / "engine.lock.toml").read_text())
    flags = lock["launch"]["flags"]
    assert flags.count("--disable-all-custom-nodes") == 1
    i = flags.index("--whitelist-custom-nodes")
    assert flags[i + 1 : i + 2] == ["p11_ipadapter"]
    packs = lock["custom_nodes"]["packs"]
    assert [p["name"] for p in packs] == ["p11_ipadapter"]
    assert packs[0]["source"] == "engine/custom_nodes/p11_ipadapter"
    # The digest in the lock is the digest of the file that ships.
    import hashlib

    digest = hashlib.sha256(PACK.read_bytes()).hexdigest()
    assert packs[0]["sha256"] == digest, "bump engine.lock.toml after editing the pack"

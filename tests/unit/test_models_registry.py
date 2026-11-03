# ruff: noqa: E501  (TOML test data reads best unwrapped)
import hashlib
import pickle
import tomllib

import pytest
from tests.fixtures.model_server import safetensors_bytes, serve

from p11.models import doctor
from p11.models.download import Downloader, DownloadItem
from p11.models.manifest import parse_manifest
from p11.models.registry import LicenceNotAccepted, ModelError, ModelManager
from p11.models.state import HashCache, LicenceStore, StateStore, dump_toml
from p11.recipe.registry import UnknownModelError

CKPT = safetensors_bytes({"model.diffusion_model.a": 64, "conditioner.embedders.1.x": 8})
VAE = safetensors_bytes({"encoder.a": 16, "decoder.b": 16})
UPS = safetensors_bytes({"feats.0.weight": 32})
SD15 = safetensors_bytes({"model.diffusion_model.a": 32, "cond_stage_model.transformer.x": 8})


def sha(b):
    return hashlib.sha256(b).hexdigest()


def manifest_text(server):
    def f(path, body, name):
        url = server.add(path, body)
        return f'files = [{{ url = "{url}", filename = "{name}", sha256 = "{sha(body)}", size = {len(body)} }}]'

    return f"""
schema_version = 1

[[model]]
id = "ckpt"
name = "Test checkpoint"
kind = "checkpoint"
base = "sdxl"
sets = ["default"]
{f("/ckpt", CKPT, "ckpt.safetensors")}
licence = {{ name = "OpenRAIL-M", url = "https://example.org/l", commercial_use = true, flags = ["use-restrictions"] }}
defaults = {{ sampler = "euler", scheduler = "normal", steps = 20, cfg = 5.0, hires_steps = 8, vae = "vae" }}

[[model]]
id = "vae"
name = "Test VAE"
kind = "vae"
base = "sdxl"
sets = ["default", "full"]
{f("/vae", VAE, "vae.safetensors")}
licence = {{ name = "MIT", url = "https://example.org/mit", commercial_use = true }}

[[model]]
id = "up"
name = "Test upscaler"
kind = "upscale"
base = "any"
scale = 4
sets = ["full"]
{f("/up", UPS, "up.safetensors")}
licence = {{ name = "CC-BY-NC-4.0", url = "https://example.org/nc", commercial_use = false, flags = ["non-commercial", "attribution"] }}
"""


@pytest.fixture
def server():
    yield from serve()


@pytest.fixture
def mgr(server, tmp_path):
    m = ModelManager(tmp_path / "models", parse_manifest(manifest_text(server), loopback_http=True))
    m.ensure_folders()
    return m


@pytest.fixture
def downloader():
    with Downloader(insecure_hosts=["127.0.0.1"], sleep=lambda s: None) as d:
        yield d


def states(m):
    return {s.id: s.state for s in m.statuses()}


def test_install_default_then_nothing_twice(mgr, downloader, server):
    assert states(mgr) == {"ckpt": "missing", "vae": "missing", "up": "missing"}
    plan = mgr.plan("default")
    assert [e.id for e in plan.to_fetch] == ["ckpt", "vae"]
    assert plan.download_bytes == len(CKPT) + len(VAE)
    report = mgr.install("default", downloader=downloader, accept_licences=True)
    assert report.downloaded == ["ckpt", "vae"]
    assert report.bytes_downloaded == len(CKPT) + len(VAE)
    assert report.accepted == ["ckpt"]  # MIT needs no acknowledgement
    assert states(mgr) == {"ckpt": "installed", "vae": "installed", "up": "missing"}
    n = len(server.requests)
    again = mgr.install("default", downloader=downloader)
    assert again.downloaded == [] and again.present == ["ckpt", "vae"]
    assert len(server.requests) == n


def test_install_by_id_pulls_its_vae(mgr, downloader):
    assert [e.id for e in mgr.resolve_target("ckpt")] == ["ckpt", "vae"]
    assert [e.id for e in mgr.resolve_target("full")] == ["ckpt", "vae", "up"]
    with pytest.raises(ModelError, match="neither a set"):
        mgr.resolve_target("nope")


def test_licence_required_and_recorded(mgr, downloader, tmp_path):
    with pytest.raises(LicenceNotAccepted, match=r"(?s)OpenRAIL-M.*--accept-licences"):
        mgr.install("default", downloader=downloader)
    assert states(mgr)["ckpt"] == "missing"
    asked = []
    with pytest.raises(LicenceNotAccepted):
        mgr.install("up", downloader=downloader, confirm=lambda e: asked.append(e.id) or False)
    assert asked == ["up"]
    mgr.install("up", downloader=downloader, confirm=lambda e: True)
    acks = mgr.licences.all()
    assert acks["up"].how == "interactive" and not acks["up"].commercial_use
    assert acks["up"].accepted_at[:2] == "20"
    data = tomllib.loads((tmp_path / "config" / "licences.toml").read_text())
    assert data["accepted"]["up"]["licence"] == "CC-BY-NC-4.0"
    assert (tmp_path / "config" / "licences.toml").stat().st_mode & 0o777 == 0o600
    # Asked only once: the second install needs no flag.
    mgr.install("up", downloader=downloader)
    assert mgr.status("up").licence_accepted


def test_licence_change_asks_again(mgr):
    mgr.licences.record([])
    from p11.models.state import Acknowledgement

    mgr.licences.record([Acknowledgement("ckpt", "Old licence", "u", True, "t", "x")])
    assert not mgr.licences.accepted("ckpt", "OpenRAIL-M")


def test_corrupt_detected_by_size_and_hash_and_repaired(mgr, downloader):
    mgr.install("default", downloader=downloader, accept_licences=True)
    path = mgr.path_of(mgr.manifest.get("ckpt"))
    data = bytearray(path.read_bytes())
    data[-1] ^= 0xFF
    path.write_bytes(bytes(data))  # same size, new mtime → cache miss
    assert mgr.status("ckpt").state == "corrupt"
    assert "SHA-256" in mgr.status("ckpt").detail
    path.write_bytes(b"short")
    assert "size" in mgr.status("ckpt").detail
    report = mgr.install("ckpt", downloader=downloader)
    assert report.repaired == ["ckpt"] and report.downloaded == ["ckpt"]
    assert mgr.status("ckpt").state == "installed"


def test_verify_ignores_the_cache(mgr, downloader):
    mgr.install("default", downloader=downloader, accept_licences=True)
    path = mgr.path_of(mgr.manifest.get("vae"))
    stat = path.stat()
    data = bytearray(path.read_bytes())
    data[-1] ^= 0xFF
    path.write_bytes(bytes(data))
    import os

    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # fool the size+mtime cache
    assert mgr.status("vae").state == "installed"
    rows = {s.id: s.state for s in mgr.verify()}
    assert rows == {"ckpt": "installed", "vae": "corrupt"}
    assert mgr.verify(["vae"])[0].state == "corrupt"


def test_join_by_hash_and_unregistered(mgr):
    (mgr.folder("vae") / "renamed.safetensors").write_bytes(VAE)
    (mgr.folder("lora") / "stray.safetensors").write_bytes(b"x" * 10)
    (mgr.folder("lora") / "half.safetensors.part").write_bytes(b"x")
    rows = {s.id: s for s in mgr.statuses()}
    assert rows["vae"].state == "installed" and rows["vae"].filename == "renamed.safetensors"
    assert rows["stray"].state == "unregistered" and rows["stray"].kind == "lora"
    assert "half" not in "".join(rows)
    assert mgr.info("vae").filename == "renamed.safetensors"


def test_copy_from_source_dir(mgr, downloader, server, tmp_path):
    src = tmp_path / "old-models"
    (src / "checkpoints").mkdir(parents=True)
    (src / "checkpoints" / "ckpt.safetensors").write_bytes(CKPT)
    (src / "vae.safetensors").write_bytes(b"wrong bytes")  # wrong size → downloaded instead
    report = mgr.install("default", downloader=downloader, accept_licences=True, source_dirs=[src])
    assert report.copied == ["ckpt"] and report.downloaded == ["vae"]
    assert [r.path for r in server.requests] == ["/vae"]
    assert mgr.path_of(mgr.manifest.get("ckpt")).read_bytes() == CKPT


def test_enable_disable_and_registry(mgr, downloader):
    reg = mgr.registry()
    with pytest.raises(UnknownModelError, match=r"missing.*p11 models install ckpt"):
        reg.get("ckpt")
    info = mgr.registry(require_installed=False).get("ckpt")
    assert info.family == "sdxl" and info.vae == "vae" and info.defaults.hires_steps == 8
    mgr.install("full", downloader=downloader, accept_licences=True)
    assert reg.get("ckpt").filename == "ckpt.safetensors"
    assert reg.get("up").scale == 4 and reg.get("up").family is None
    mgr.set_enabled("ckpt", False)
    assert not mgr.status("ckpt").enabled
    with pytest.raises(UnknownModelError, match="disabled"):
        reg.get("ckpt")
    mgr.set_enabled("ckpt", True)
    assert reg.get("ckpt")
    with pytest.raises(ModelError, match="No model"):
        mgr.set_enabled("nope", True)
    with pytest.raises(UnknownModelError, match="not installed or not in the manifest"):
        reg.get("nope")


def test_remove_manifest_model(mgr, downloader):
    mgr.install("default", downloader=downloader, accept_licences=True)
    msg = mgr.remove("vae")
    assert "Deleted" in msg and mgr.status("vae").state == "missing"
    assert "not installed" in mgr.remove("vae")
    with pytest.raises(ModelError):
        mgr.remove("nope")


def test_add_user_safetensors_detects_kind_and_base(mgr, tmp_path):
    src = tmp_path / "My Model v2.safetensors"
    src.write_bytes(SD15)
    with pytest.raises(ModelError, match=r"invalid file name|not a file"):
        mgr.add(str(tmp_path / "missing.safetensors"))
    src2 = tmp_path / "MyModel_v2.safetensors"
    src2.write_bytes(SD15)
    s = mgr.add(str(src2))
    assert (s.id, s.kind, s.base, s.state, s.origin) == (
        "mymodel_v2".replace("_", "-"),
        "checkpoint",
        "sd15",
        "user-added",
        "user",
    )
    assert (mgr.folder("checkpoint") / "MyModel_v2.safetensors").read_bytes() == SD15
    info = mgr.info(s.id)
    assert info.family == "sd15" and info.defaults.steps == 25
    with pytest.raises(ModelError, match="already exists"):
        mgr.add(str(src2))
    assert src.exists()


def test_add_matching_manifest_hash_installs_curated_entry(mgr, tmp_path):
    src = tmp_path / "whatever.safetensors"
    src.write_bytes(VAE)
    s = mgr.add(str(src))
    assert (s.id, s.state, s.origin) == ("vae", "installed", "manifest")
    assert mgr.state.load().user == {}


def test_add_refuses_pickle_unless_allowed(mgr, tmp_path):
    src = tmp_path / "evil.safetensors"  # the extension lies
    src.write_bytes(pickle.dumps({"weights": [1, 2, 3]}))
    with pytest.raises(ModelError, match=r"pickle-based.*arbitrary code.*--allow-pickle"):
        mgr.add(str(src), kind="lora")
    assert not any(mgr.folder("lora").iterdir())
    warnings = []
    s = mgr.add(str(src), kind="lora", allow_pickle=True, warn=warnings.append)
    assert "arbitrary code" in warnings[0]
    assert s.format == "pickle" and mgr.info(s.id).kind == "lora"
    assert [p.code for p in doctor.check(mgr, free_space=lambda p: 10**12)][-1] == "models.pickle"


def test_add_refuses_unknown_formats_and_unknown_kind(mgr, tmp_path):
    src = tmp_path / "notes.safetensors"
    src.write_bytes(b"hello, I am text")
    with pytest.raises(ModelError, match="not a safetensors or GGUF"):
        mgr.add(str(src))
    up = tmp_path / "up2.safetensors"
    up.write_bytes(safetensors_bytes({"body.0.weight": 8}))
    with pytest.raises(ModelError, match="pass --kind"):
        mgr.add(str(up))
    with pytest.raises(ModelError, match="Unknown kind"):
        mgr.add(str(up), kind="weird")
    assert mgr.add(str(up), kind="upscale", model_id="my-up").id == "my-up"


def test_add_link_and_remove_keeps_file(mgr, tmp_path):
    src = tmp_path / "lora.safetensors"
    src.write_bytes(safetensors_bytes({"lora_unet_a.lora_up.weight": 4, "lora_te2_b.alpha": 1}))
    s = mgr.add(str(src), link=True)
    assert s.kind == "lora" and s.base == "sdxl"
    link = mgr.folder("lora") / "lora.safetensors"
    assert link.is_symlink()
    assert "left in place" in mgr.remove(s.id)
    assert link.is_symlink() and src.exists()


def test_remove_user_model_with_delete_file(mgr, tmp_path):
    src = tmp_path / "l.safetensors"
    src.write_bytes(safetensors_bytes({"lora_unet_a.lora_up.weight": 4}))
    s = mgr.add(str(src))
    mgr.set_enabled(s.id, False)
    assert "deleted" in mgr.remove(s.id, delete_file=True)
    assert not (mgr.folder("lora") / "l.safetensors").exists()
    assert mgr.state.load().disabled == []


def test_user_model_missing_or_changed(mgr, tmp_path):
    src = tmp_path / "l.safetensors"
    src.write_bytes(safetensors_bytes({"lora_unet_a.lora_up.weight": 4}))
    s = mgr.add(str(src))
    dest = mgr.folder("lora") / "l.safetensors"
    dest.write_bytes(safetensors_bytes({"lora_unet_a.lora_up.weight": 5}))
    assert mgr.status(s.id).state == "corrupt"
    with pytest.raises(UnknownModelError, match="missing or changed"):
        mgr.info(s.id)
    dest.unlink()
    assert mgr.status(s.id).state == "missing"
    codes = {p.code for p in doctor.check(mgr, free_space=lambda p: 10**12)}
    assert "models.user-missing" in codes


def test_add_from_url(mgr, server, downloader):
    url = server.add(
        "/files/extra-vae.safetensors", safetensors_bytes({"encoder.q": 3, "decoder.q": 3})
    )
    s = mgr.add(url, downloader=downloader)
    assert s.kind == "vae" and s.origin == "user"
    assert mgr.state.load().user[s.id].source == url
    assert not any((mgr.root / ".incoming").iterdir())
    with pytest.raises(ModelError, match="--link only"):
        mgr.add(url, downloader=downloader, link=True)
    with pytest.raises(ModelError, match="downloader is needed"):
        mgr.add(url)


def test_url_add_of_pickle_cleans_up(mgr, server, downloader):
    url = server.add("/evil.ckpt", pickle.dumps([1]))
    with pytest.raises(ModelError, match="pickle"):
        mgr.add(url, downloader=downloader, kind="checkpoint")
    assert not any((mgr.root / ".incoming").iterdir())


def test_doctor(mgr, downloader):
    probs = doctor.check(mgr, free_space=lambda p: 10**12)
    assert [p.code for p in probs] == ["models.missing-default", "models.missing-default"]
    assert probs[0].severity == "error" and "p11 models install default" in probs[0].hint
    mgr.install("default", downloader=downloader, accept_licences=True)
    assert doctor.check(mgr, free_space=lambda p: 10**12) == []
    mgr.path_of(mgr.manifest.get("vae")).write_bytes(b"x")
    probs = doctor.check(mgr, free_space=lambda p: 10**9)
    assert [p.code for p in probs] == ["models.corrupt", "models.disk-low"]
    assert probs[0].as_json()["hint"] == "Run `p11 models install vae` to replace it."


def test_doctor_on_missing_root(tmp_path, server):
    m = ModelManager(
        tmp_path / "nowhere" / "models", parse_manifest(manifest_text(server), loopback_http=True)
    )
    probs = doctor.check(m, free_space=lambda p: 10**12)
    assert {p.code for p in probs} == {"models.missing-default"}


def test_extra_model_paths(mgr, tmp_path):
    engine = tmp_path / "engine"
    assert mgr.write_extra_model_paths(engine)
    text = (engine / "extra_model_paths.yaml").read_text()
    assert f"base_path: {mgr.root}" in text and "upscale_models: upscale/" in text
    assert not mgr.write_extra_model_paths(engine)


def test_state_store_roundtrip(tmp_path):
    store = StateStore(tmp_path / "models.toml")
    st = store.load()
    assert st.disabled == [] and st.user == {}
    st.disabled = ["b", "a", "a"]
    store.save(st)
    assert store.load().disabled == ["a", "b"]


def test_dump_toml_escapes():
    text = dump_toml(
        {"x": 'quote " and \\ back', "t": {"a.b": {"n": 1, "f": 1.5, "ok": True, "l": ["q"]}}}
    )
    data = tomllib.loads(text)
    assert data["x"] == 'quote " and \\ back'
    assert data["t"]["a.b"] == {"n": 1, "f": 1.5, "ok": True, "l": ["q"]}
    with pytest.raises(TypeError):
        dump_toml({"x": object()})


def test_hash_cache(tmp_path):
    cache = HashCache(tmp_path / "h.json")
    f = tmp_path / "f"
    f.write_bytes(b"abc")
    assert cache.cached(f) is None
    digest = cache.sha256(f)
    assert HashCache(tmp_path / "h.json").cached(f) == digest
    cache.forget(f)
    assert HashCache(tmp_path / "h.json").cached(f) is None
    (tmp_path / "h.json").write_text("not json")
    assert HashCache(tmp_path / "h.json").cached(f) is None


def test_default_store_locations(tmp_path):
    assert LicenceStore().path == tmp_path / "config" / "licences.toml"
    assert StateStore().path == tmp_path / "config" / "models.toml"
    assert HashCache().path == tmp_path / "cache" / "model-hashes.json"


def test_download_item_part_name(tmp_path):
    assert DownloadItem("https://x/y", tmp_path / "a.safetensors", None, None).part.name == (
        "a.safetensors.part"
    )

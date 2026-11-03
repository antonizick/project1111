"""Job queue and runner on the FakeEngine: chaining, cancel, OOM retry, restart, thermal pause."""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass, field

import pytest
from PIL import Image
from tests.helpers import recipe
from tests.studio import eventually, generate_recipe, png_bytes, studio_client

from p11.engine.fake import FakeConfig, FakeEngine
from p11.gpu.telemetry import GpuSample, ThermalGuard
from p11.jobs.events import EventBus
from p11.jobs.queue import JobQueue, ThermalWatch
from p11.jobs.runner import JobControl, Runner, gallery_ref
from p11.jobs.store import INTERRUPTED_CODE, Job, JobStore
from p11.media.inputs import InputStore
from p11.outputs import metadata
from p11.outputs.index import GalleryIndex
from p11.recipe.model import FixedSeed, Generate, IncrementSeed, Slot, Upscale
from p11.recipe.registry import PROVISIONAL_DEFAULT_SET, StaticRegistry


def submit(c, body):  # type: ignore[no-untyped-def]
    r = c.post("/api/jobs", headers=c.auth, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_wallpaper_job_is_saved_indexed_and_round_trips(tmp_path):
    with studio_client(tmp_path) as c:
        body = generate_recipe(steps=[Generate(prompt="a misty valley", aspect="16:9-1920x1080")])
        job = submit(c, {"recipe": body})
        assert job["state"] == "queued"
        done = c.wait_job(job["id"])
        assert done["state"] == "done" and done["progress"] == 1.0, done
        (image_id,) = done["images"]
        page = c.get("/api/gallery", headers=c.auth).json()
        assert page["total"] == 1 and page["items"][0]["id"] == image_id
        item = page["items"][0]
        assert (item["width"], item["height"]) == (1920, 1080)
        assert item["template"] is None and item["seed"] == 1111
        path = tmp_path / "pictures" / item["path"]
        assert path.parent.name == "adhoc" and path.name.endswith("-1111.png")
        assert path.stat().st_mode & 0o777 == 0o600
        assert metadata.read_recipe_from_png(path).model_dump(mode="json") == body
        run = c.get(f"/api/images/{image_id}/recipe", headers=c.auth).json()
        assert run["seed"] == 1111 and run["engine_version"] == "0.43.0"
        assert run["model_hashes"]["realvisxl5-lightning"]
        with Image.open(io.BytesIO(c.get(item["url"], headers=c.auth).content)) as img:
            assert img.size == (1920, 1080)


def test_multi_step_chaining_and_parents(tmp_path):
    steps = [Generate(prompt="a red fox", aspect="1:1-1024"), Upscale(scale=2.0)]
    with studio_client(tmp_path) as c:
        done = c.wait_job(submit(c, {"recipe": generate_recipe(steps=steps),
                                     "template": "fox"})["id"])  # fmt: skip
        assert done["state"] == "done", done
        first, second = done["images"]
        a = c.get(f"/api/images/{first}/info", headers=c.auth).json()
        b = c.get(f"/api/images/{second}/info", headers=c.auth).json()
        assert a["path"].endswith("-00-generate.png") and "/fox/" in a["path"]
        assert b["parent_id"] == first and (b["width"], b["height"]) == (2048, 2048)
        # the upscale graph was fed the generate step's PNG
        assert c.engine.uploads
        record = metadata.read_sidecar(metadata.sidecar_path(tmp_path / "pictures" / b["path"]))
        assert [o.step_type for o in record.step_outputs] == ["generate", "upscale"]
        assert record.parent == a["path"] and record.template == "fox"
        # a follow-up job made from an earlier image keeps the link
        follow = c.wait_job(submit(c, {"recipe": generate_recipe(), "parent": second})["id"])
        child = c.get(f"/api/images/{follow['images'][0]}/info", headers=c.auth).json()
        assert child["parent_id"] == second


def test_batch_count_increments_seeds(tmp_path):
    body = generate_recipe(seed=IncrementSeed(start=10))
    with studio_client(tmp_path) as c:
        done = c.wait_job(submit(c, {"recipe": body, "count": 3})["id"])
        seeds = sorted(c.get(f"/api/images/{i}/info", headers=c.auth).json()["seed"]
                       for i in done["images"])  # fmt: skip
        assert seeds == [10, 11, 12]


def test_batch_size_saves_every_image(tmp_path):
    steps = [Generate(prompt="a cat", aspect="1:1-1024", batch_size=2)]
    with studio_client(tmp_path) as c:
        done = c.wait_job(submit(c, {"recipe": generate_recipe(steps=steps)})["id"])
        assert len(done["images"]) == 2


def test_image_slot_binding_uses_the_upload(tmp_path):
    steps = [Upscale(image_slot="photo", scale=2.0)]
    body = generate_recipe(steps=steps, slots=(Slot(name="photo", kind="image"),))
    with studio_client(tmp_path) as c:
        up = c.post("/api/uploads", headers=c.auth, content=png_bytes((300, 200))).json()
        done = c.wait_job(
            submit(c, {"recipe": body, "bindings": {"photo": {"ref": up["id"]}}})["id"]
        )
        assert done["state"] == "done", done
        info = c.get(f"/api/images/{done['images'][0]}/info", headers=c.auth).json()
        assert (info["width"], info["height"]) == (600, 400)
        # an earlier gallery image works as the input too
        again = submit(c, {"recipe": body, "bindings": {"photo": {"ref": gallery_ref(info["id"])}}})
        assert c.wait_job(again["id"])["state"] == "done"


def test_submit_errors_are_plain_4xx(tmp_path):
    slots = (Slot(name="subject", kind="text"),)
    needs_text = generate_recipe(steps=[Generate(prompt="{{subject}} at night")], slots=slots)
    needs_photo = generate_recipe(steps=[Upscale(image_slot="photo")],
                                  slots=(Slot(name="photo", kind="image"),))  # fmt: skip
    with studio_client(tmp_path) as c:
        r = c.post("/api/jobs", headers=c.auth, json={"recipe": needs_text})
        assert r.status_code == 422 and r.json()["code"] == "recipe.slot"
        assert "subject" in r.json()["message"]
        r = c.post(
            "/api/jobs",
            headers=c.auth,
            json={"recipe": needs_photo, "bindings": {"photo": {"ref": "img-" + "a" * 32}}},
        )
        assert r.status_code == 422 and r.json()["code"] == "input.missing"
        r = c.post(
            "/api/jobs",
            headers=c.auth,
            json={"recipe": needs_photo, "bindings": {"photo": {"ref": "../../etc/passwd"}}},
        )
        assert r.status_code == 422
        r = c.post("/api/jobs", headers=c.auth, json={"recipe": {**generate_recipe(), "steps": []}})
        assert r.status_code == 422 and r.json()["code"] == "recipe.invalid"
        r = c.post("/api/jobs", headers=c.auth, json={"recipe": generate_recipe(), "count": 99})
        assert r.status_code == 422 and r.json()["code"] == "request.invalid"
        r = c.post("/api/jobs", headers=c.auth, json={"recipe": generate_recipe(), "parent": 404})
        assert r.status_code == 404
        assert c.get("/api/jobs/nope", headers=c.auth).status_code == 404
        assert c.post("/api/jobs/nope/cancel", headers=c.auth).status_code == 404


def test_missing_model_is_a_4xx_with_install_hint(tmp_path):
    body = generate_recipe(steps=[Generate(prompt="x", model={"manifest_id": "not-installed"})])
    with studio_client(tmp_path) as c:
        r = c.post("/api/jobs", headers=c.auth, json={"recipe": body})
        assert r.status_code == 409
        assert r.json()["code"] == "models.missing"
        assert "p11 models install" in r.json()["hint"]


def test_cancel_running_and_queued_jobs(tmp_path):
    engine = FakeEngine(FakeConfig(step_delay=0.05))
    with studio_client(tmp_path, engine=engine) as c:
        running = submit(c, {"recipe": generate_recipe()})
        queued = submit(c, {"recipe": generate_recipe()})
        eventually(lambda: c.get(f"/api/jobs/{running['id']}", headers=c.auth).json()["state"]
                   == "running")  # fmt: skip
        r = c.post(f"/api/jobs/{queued['id']}/cancel", headers=c.auth)
        assert r.json()["state"] == "cancelled"
        c.post(f"/api/jobs/{running['id']}/cancel", headers=c.auth)
        done = c.wait_job(running["id"])
        assert done["state"] == "cancelled" and done["images"] == []
        assert c.post(f"/api/jobs/{running['id']}/cancel", headers=c.auth).json()["state"] == (
            "cancelled"
        )
        listed = {j["id"]: j["state"] for j in c.get("/api/jobs", headers=c.auth).json()}
        assert listed == {running["id"]: "cancelled", queued["id"]: "cancelled"}


def test_oom_retry_succeeds_with_a_note(tmp_path):
    engine = FakeEngine()
    engine.fail_next("oom")
    with studio_client(tmp_path, engine=engine) as c:
        done = c.wait_job(submit(c, {"recipe": generate_recipe()})["id"])
        assert done["state"] == "done"
        assert "low-memory" in done["note"]
        assert engine.vram_mode == "lowvram"


def test_oom_twice_fails_with_the_plain_message(tmp_path):
    engine = FakeEngine()
    engine.fail_next("oom", count=2)
    with studio_client(tmp_path, engine=engine) as c:
        done = c.wait_job(submit(c, {"recipe": generate_recipe()})["id"])
        assert done["state"] == "failed"
        assert done["error"]["code"] == "engine.oom"
        assert done["error"]["message"].startswith("Out of GPU memory")
        assert "smaller preset" in done["error"]["hint"]


@pytest.mark.parametrize(("kind", "code"), [("crash", "engine.crashed"),
                                            ("execution", "engine.execution"),
                                            ("validation", "engine.validation")])  # fmt: skip
def test_engine_failures_map_to_problems(tmp_path, kind, code):
    engine = FakeEngine()
    engine.fail_next(kind)
    with studio_client(tmp_path, engine=engine) as c:
        done = c.wait_job(submit(c, {"recipe": generate_recipe()})["id"])
        assert done["state"] == "failed" and done["error"]["code"] == code
        assert done["error"]["hint"]
        # the queue keeps working afterwards
        assert c.wait_job(submit(c, {"recipe": generate_recipe()})["id"])["state"] == "done"


def test_restart_marks_interrupted_jobs(tmp_path):
    store = JobStore(tmp_path / "data" / "jobs.db")
    for state in ("queued", "running", "paused", "done"):
        store.put(Job(id=state, state=state, recipe=generate_recipe(), bindings={}))
    store.close()
    with studio_client(tmp_path) as c:
        jobs = {j["id"]: j for j in c.get("/api/jobs", headers=c.auth).json()}
        for i in ("queued", "running", "paused"):
            assert jobs[i]["state"] == "failed"
            assert jobs[i]["error"]["code"] == INTERRUPTED_CODE
        assert jobs["done"]["state"] == "done"
        assert sorted(c.studio.queue.interrupted) == ["paused", "queued", "running"]
    assert (tmp_path / "data" / "jobs.db").stat().st_mode & 0o777 == 0o600


def test_job_summaries_hold_no_prompt_text(tmp_path):
    with studio_client(tmp_path) as c:
        job = submit(c, {"recipe": generate_recipe("secret prompt words")})
        assert "secret" not in str(job)


# -- thermal pause and idle engine --------------------------------------------------------------


@dataclass
class TempSampler:
    temps: list[float]
    name: str = "fake"
    calls: list[float] = field(default_factory=list)

    def sample(self) -> GpuSample:
        t = self.temps.pop(0) if len(self.temps) > 1 else self.temps[0]
        self.calls.append(t)
        return GpuSample(1000, 8192, int(t), 50.0, 1500, 6000, (), 0.0)

    def close(self) -> None:
        pass


def test_long_job_pauses_while_hot_and_resumes(tmp_path):
    sampler = TempSampler([70, 90, 89, 79, 70])
    with studio_client(tmp_path, sampler=sampler) as c:
        c.studio.queue.thermal.poll = 0.01
        states = []

        def watch() -> bool:
            states.append(c.get(f"/api/jobs/{job['id']}", headers=c.auth).json()["state"])
            return states[-1] == "done"

        job = submit(c, {"recipe": generate_recipe(seed=IncrementSeed(start=1)), "count": 3})
        eventually(watch)
        events_seen = [e for e in c.studio.bus._replay if e.type == "job"]
        seen = [e.data["state"] for e in events_seen if e.data["id"] == job["id"]]
        assert "paused" in seen and seen[-1] == "done"
        paused = next(e.data for e in events_seen if e.data["state"] == "paused")
        assert "°C" in paused["note"]


async def test_thermal_watch_without_reading_is_a_no_op():
    class Broken:
        name = "broken"

        def sample(self) -> GpuSample:
            raise RuntimeError("nvml gone")

        def close(self) -> None:
            pass

    watch = ThermalWatch(Broken(), ThermalGuard(87, 80))
    paused: list[float] = []
    await watch.wait(JobControl(), paused.append, lambda: None)
    assert paused == []


async def test_cancel_during_thermal_pause(tmp_path):
    watch = ThermalWatch(TempSampler([95]), ThermalGuard(87, 80), poll=0.01)
    control = JobControl(lambda ctl: watch.wait(ctl, lambda t: None, lambda: None))
    task = asyncio.create_task(control.checkpoint(long=True))
    await asyncio.sleep(0.05)
    control.cancel()
    from p11.engine.base import EngineInterrupted

    with pytest.raises(EngineInterrupted):
        await task


def _queue(tmp_path, engine, **kw):  # type: ignore[no-untyped-def]
    gallery = GalleryIndex(tmp_path / "g.db")
    runner = Runner(engine, lambda: PROVISIONAL_DEFAULT_SET, tmp_path / "out", gallery,
                    InputStore(tmp_path / "in"))  # fmt: skip
    return JobQueue(JobStore(tmp_path / "j.db"), runner, EventBus(), **kw)


async def test_idle_engine_is_stopped_and_restarted_lazily(tmp_path):
    engine = FakeEngine()
    q = _queue(tmp_path, engine, idle_stop=0.1)
    await q.start()
    try:
        job = q.submit(generate_recipe(), {})
        for _ in range(200):
            if (q.get(job.id) or job).state == "done":
                break
            await asyncio.sleep(0.01)
        assert engine.state == "ready" and engine.starts == 1
        await asyncio.sleep(0.3)
        assert engine.state == "stopped"
        job2 = q.submit(generate_recipe(), {})
        for _ in range(200):
            if (q.get(job2.id) or job2).state == "done":
                break
            await asyncio.sleep(0.01)
        assert q.get(job2.id).state == "done" and engine.starts == 2
    finally:
        await q.stop()
    assert engine.state == "stopped"


async def test_lowvram_mode_is_reset_when_idle(tmp_path):
    engine = FakeEngine()
    engine.fail_next("oom")
    q = _queue(tmp_path, engine, idle_stop=10, lowvram_reset=0.1)
    await q.start()
    try:
        job = q.submit(generate_recipe(), {})
        for _ in range(200):
            if (q.get(job.id) or job).state == "done":
                break
            await asyncio.sleep(0.01)
        assert engine.vram_mode == "lowvram"
        await asyncio.sleep(0.3)
        assert engine.vram_mode == "dynamic" and engine.state == "ready"
    finally:
        await q.stop()


async def test_stopped_lowvram_engine_starts_dynamic(tmp_path):
    engine = FakeEngine(vram_mode="lowvram")
    q = _queue(tmp_path, engine, idle_stop=10)
    await q.start()
    try:
        job = q.submit(generate_recipe(), {})
        for _ in range(200):
            if (q.get(job.id) or job).state == "done":
                break
            await asyncio.sleep(0.01)
        assert engine.vram_mode == "dynamic"
    finally:
        await q.stop()


async def test_queue_limit_and_count_bounds(tmp_path, monkeypatch):
    from p11.jobs import queue as queue_mod

    q = _queue(tmp_path, FakeEngine())
    with pytest.raises(ValueError):
        q.submit(generate_recipe(), {}, count=0)
    monkeypatch.setattr(queue_mod, "QUEUE_LIMIT", 1)
    q.submit(generate_recipe(), {})
    with pytest.raises(queue_mod.QueueFull):
        q.submit(generate_recipe(), {})


def test_static_registry_is_the_fake_default():
    assert isinstance(PROVISIONAL_DEFAULT_SET, StaticRegistry)
    assert recipe(seed=FixedSeed(value=3)).seed.value == 3

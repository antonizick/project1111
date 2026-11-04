import { expect, it, vi } from "vitest";
import { EventStream } from "../api/events";
import { FakeSource, image, job } from "../test/fakes";
import { initialState, reduce, type StudioState } from "./studio";

const ev = (s: StudioState, type: string, data: unknown) =>
  reduce(s, { type: "event", event: { type: type as never, data } });

it("follows jobs, progress, previews, images, GPU and deletes", () => {
  let s = ev(initialState, "hello", { jobs: [job()] });
  expect(s.connected).toBe(true);
  expect(s.jobs.job1?.state).toBe("queued");
  s = ev(s, "job", job({ state: "running" }));
  s = ev(s, "progress", {
    job: "job1",
    run: 0,
    runs: 1,
    graph: 0,
    graphs: 1,
    progress: 0.4,
    step: 2,
    total: 5,
    title: "base",
  });
  // an `executing` event (no step) keeps the step count of the same graph
  s = ev(s, "progress", {
    job: "job1",
    run: 0,
    runs: 1,
    graph: 0,
    graphs: 1,
    progress: 0.5,
    title: "hires",
  });
  expect(s.progress.job1).toMatchObject({ step: 2, total: 5, title: "hires" });
  expect(s.jobs.job1?.progress).toBe(0.5);
  s = ev(s, "preview", { job: "job1", mime: "image/jpeg", data: "QUJD" });
  expect(s.previews.job1).toBe("data:image/jpeg;base64,QUJD");
  const rev = s.galleryRev;
  s = ev(s, "image", { job: "job1", image: image(3) });
  expect(s.images[3]?.id).toBe(3);
  expect(s.galleryRev).toBe(rev + 1);
  s = ev(s, "job", job({ state: "done", images: [3], progress: 1 }));
  expect(s.progress.job1).toBeUndefined();
  expect(s.previews.job1).toBeUndefined();
  s = ev(s, "gpu", {
    vram_used_mib: 4096,
    vram_total_mib: 8192,
    temp_c: 71,
    power_w: 50,
    throttle_reasons: [],
  });
  expect(s.gpu?.temp_c).toBe(71);
  s = ev(s, "deleted", { image: 3 });
  expect(s.images[3]).toBeUndefined();
  s = reduce(s, { type: "cache", images: [image(9)] });
  expect(s.images[9]).toBeDefined();
  expect(s.galleryRev).toBe(rev + 2); // caching is not a gallery change
  s = reduce(s, { type: "submitted", jobs: [job({ id: "j2" })], model: "juggernautxl9" });
  expect(s.currentModel).toBe("juggernautxl9");
  expect(ev(s, "image", { job: null, image: null })).toBe(s);
});

it("reconnects with backoff after the stream closes", () => {
  vi.useFakeTimers();
  const status: boolean[] = [];
  const events: string[] = [];
  const stream = new EventStream({
    onEvent: (e) => events.push(e.type),
    onStatus: (c) => status.push(c),
    create: (url) => new FakeSource(url),
    backoff: [100, 500],
  });
  stream.start();
  const first = FakeSource.last!;
  first.onopen?.(new Event("open"));
  first.emit("job", job());
  first.listeners.get("gpu")?.[0]?.(new MessageEvent("gpu", { data: "not json" }));
  expect(events).toEqual(["job"]);
  first.readyState = 0; // the browser is retrying by itself: no new source
  first.onerror?.(new Event("error"));
  expect(FakeSource.last).toBe(first);
  first.readyState = 2;
  first.onerror?.(new Event("error"));
  vi.advanceTimersByTime(100);
  const second = FakeSource.last!;
  expect(second).not.toBe(first);
  second.readyState = 2;
  second.onerror?.(new Event("error"));
  vi.advanceTimersByTime(499);
  expect(FakeSource.last).toBe(second);
  vi.advanceTimersByTime(1);
  expect(FakeSource.last).not.toBe(second);
  expect(status).toEqual([true, false, false, false]);
  stream.stop();
  expect(FakeSource.last!.closed).toBe(true);
  vi.useRealTimers();
});

it("a late POST response does not undo the state the stream already delivered", () => {
  // The job starts before the browser reads the POST response (Phase 16 fix of the Phase 09 bug).
  let s = ev(initialState, "job", job({ state: "running" }));
  s = reduce(s, { type: "submitted", jobs: [job({ state: "queued" })] });
  expect(s.jobs.job1?.state).toBe("running");
  // A job the stream has not mentioned yet is taken from the response.
  s = reduce(s, { type: "submitted", jobs: [job({ id: "job2", state: "queued" })] });
  expect(s.jobs.job2?.state).toBe("queued");
  // Later stream events still apply.
  s = ev(s, "job", job({ state: "done" }));
  expect(s.jobs.job1?.state).toBe("done");
});

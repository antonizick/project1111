// Video view (Phase 13): clip + face upload, target face picked on the first frame, the swap
// request body, frame progress, the result player and Resume for interrupted jobs.

import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "../../App";
import type { Upload, VideoJob, VideoRequest } from "../../api/types";
import {
  baseRoutes,
  createSource,
  FakeSource,
  job,
  mockApi,
  Problem,
  type Route,
} from "../../test/fakes";

beforeEach(() => {
  sessionStorage.setItem("p11.token", "tok-abcdefghijkl");
  vi.stubGlobal(
    "URL",
    Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => undefined }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const videoJob = (over: Partial<VideoJob> = {}): VideoJob => ({
  ...job({ kind: "video", name: "Video face-swap" }),
  record_job: "job1",
  stage: "swapped",
  frames: 10,
  swapped: 5,
  pass_through: 1,
  seconds: 1,
  fps: 10,
  width: 160,
  height: 120,
  timings: {},
  resumable: false,
  file: null,
  ...over,
});

const uploadRoute: Route = (_init, url) => {
  const kind = url.searchParams.get("kind") ?? "image";
  const base: Upload = {
    id: kind === "video" ? "vid-1" : "img-1",
    kind,
    width: 160,
    height: 120,
    seconds: kind === "video" ? 30 : null,
    warnings: [],
  };
  return base;
};

const VIDEO_ROUTES: Record<string, Route> = {
  "POST /api/uploads": uploadRoute,
  "POST /api/video/frame": () => new Blob(["png"]),
  "POST /api/video/detect": () => ({
    faces: [
      { box: [0.3, 0.1, 0.7, 0.6], score: 0.99 },
      { box: [0.05, 0.5, 0.2, 0.8], score: 0.8 },
    ],
    width: 160,
    height: 120,
  }),
  "GET /api/video/jobs": () => [],
  "GET /api/video/jobs/job1": () =>
    videoJob({ stage: "stitched", file: "/api/video/jobs/job1/file" }),
};

async function start(routes: Record<string, Route> = {}) {
  const api = mockApi({ ...baseRoutes(), ...VIDEO_ROUTES, ...routes });
  render(<App createSource={createSource} />);
  await screen.findByRole("button", { name: "Photoreal" });
  act(() => FakeSource.last!.onopen?.(new Event("open")));
  fireEvent.click(screen.getByRole("button", { name: "Video" }));
  return api;
}

const emit = (type: string, data: unknown) => act(() => FakeSource.last!.emit(type, data));

/** Every view stays mounted (hidden), so queries are scoped to the Video form. */
const form = () => screen.getByRole("form", { name: "Video" });

function setFile(label: string, file: File) {
  const input = within(form()).getByLabelText(label);
  fireEvent.change(input, { target: { files: [file] } });
}

const clipFile = () => new File([new Blob(["clip"])], "clip.mp4", { type: "video/mp4" });
const faceFile = () => new File([new Blob(["face"])], "me.png", { type: "image/png" });

it("uploads a clip and a face, picks the target face and submits the swap", async () => {
  const user = userEvent.setup();
  const { calls } = await start({ "POST /api/video/jobs": () => videoJob() });
  setFile("Clip", clipFile());
  await screen.findByText("Largest face in every frame (P11 follows it).");
  setFile("Face photo", faceFile());
  const picker = within(form()).getByRole("group", { name: "Face to swap onto" });
  fireEvent.click(within(picker).getByRole("button", { name: "Face 2" }));
  await user.selectOptions(within(form()).getByLabelText("Quality"), "good");
  fireEvent.click(within(form()).getByRole("button", { name: "Swap faces" }));
  await screen.findByText("Waiting in the queue");

  const submit = calls.find((c) => c.method === "POST" && c.path === "/api/video/jobs");
  const body = submit?.body as VideoRequest;
  expect(body).toMatchObject({
    video: "vid-1",
    face: "img-1",
    quality: "good",
    target_face: 1,
    source_face_index: 0,
    confirm_limits: false,
    smooth: false,
    keep_frames: false,
  });
});

it("shows frame progress, the result player and Download when the job is done", async () => {
  await start({ "POST /api/video/jobs": () => videoJob() });
  setFile("Clip", clipFile());
  await within(form()).findByRole("group", { name: "Face to swap onto" });
  setFile("Face photo", faceFile());
  await within(form()).findByRole("img", { name: "me.png" }); // the upload has settled
  fireEvent.click(within(form()).getByRole("button", { name: "Swap faces" }));
  await screen.findByText("Waiting in the queue");

  emit("job", videoJob({ state: "running", updated_at: new Date().toISOString() }));
  emit("progress", {
    job: "job1",
    run: 0,
    runs: 1,
    progress: 0.5,
    step: 5,
    total: 10,
    title: "Swapping faces",
  });
  expect(screen.getByText(/frame 5\/10/)).toBeVisible();
  expect(screen.getByRole("progressbar", { name: "Job progress" })).toBeVisible();

  emit("job", videoJob({ state: "done", progress: 1, swapped: 10 }));
  const download = await screen.findByRole("button", { name: "Download" });
  expect(download).toBeVisible();
  const player = document.querySelector(".result video") as HTMLVideoElement | null;
  expect(player?.getAttribute("src")).toBe("/api/video/jobs/job1/file");
  expect(screen.getByText(/10 frames \(1 kept as they were\)/)).toBeVisible();
});

it("warns about long clips and asks for confirmation before running them", async () => {
  const { calls } = await start({
    "POST /api/uploads": (_init, url) =>
      url.searchParams.get("kind") === "video"
        ? {
            id: "vid-1",
            kind: "video",
            width: 1920,
            height: 1080,
            seconds: 120,
            warnings: ["Longer than 60 s: face-swapping it will take a long time."],
          }
        : { id: "img-1", kind: "image", width: 64, height: 64, seconds: null, warnings: [] },
    // The server refuses an unconfirmed over-limits clip (R13), like the real route.
    "POST /api/video/jobs": (init) => {
      const body = JSON.parse(String(init.body)) as VideoRequest;
      return body.confirm_limits
        ? videoJob()
        : new Problem(422, {
            code: "video.invalid",
            message: "This clip is over the recommended limits (60 s, 1080p).",
            hint: "Check the clip and the video settings.",
          });
    },
  });
  setFile("Clip", clipFile());
  await within(form()).findByRole("group", { name: "Over the recommended limits" });
  expect(within(form()).getByText(/Longer than 60 s/)).toBeVisible();
  expect(within(form()).getByText(/roughly \d+ minutes of work/)).toBeVisible();
  setFile("Face photo", faceFile());
  await within(form()).findByRole("img", { name: "me.png" }); // the upload has settled
  fireEvent.click(within(form()).getByRole("button", { name: "Swap faces" }));
  await screen.findByText(/This clip is over the recommended limits/); // the refusal toast
  let submit = calls.filter((c) => c.method === "POST" && c.path === "/api/video/jobs").pop();
  expect((submit?.body as VideoRequest).confirm_limits).toBe(false);

  fireEvent.click(within(form()).getByLabelText(/I understand, run it anyway/));
  fireEvent.click(within(form()).getByRole("button", { name: "Swap faces" }));
  await screen.findByText("Waiting in the queue");
  submit = calls.filter((c) => c.method === "POST" && c.path === "/api/video/jobs").pop();
  expect((submit?.body as VideoRequest).confirm_limits).toBe(true);
});

it("lists interrupted runs and resumes them at the last finished frame", async () => {
  const user = userEvent.setup();
  await start({
    "GET /api/video/jobs": () => [
      videoJob({ state: "failed", resumable: true, swapped: 6, file: null }),
    ],
    "POST /api/video/jobs/job1/resume": () => videoJob({ id: "job2" }),
    "GET /api/video/jobs/job2": () => videoJob({ id: "job2", file: null }),
  });
  const list = await screen.findByRole("region", { name: "Recent video swaps" }); // outside the form
  expect(within(list).getByText(/interrupted/)).toBeVisible();
  await user.click(within(list).getByRole("button", { name: "Resume" }));
  await screen.findByText("Waiting in the queue");
});

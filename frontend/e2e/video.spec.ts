// Video face-swap (Phase 13): the whole flow against `p11 serve --fake` — clip in, face picked on
// the first frame, Swap, frame progress, and a playable MP4 with Download. The face pipeline runs
// as the deterministic stubs here; the real face models run in `tests/gpu/` and the laptop
// acceptance run. Every request must stay on 127.0.0.1 (S1).

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { openStudio } from "./studio";

function madeByFfmpeg(args: string[], ext: string): Buffer {
  const dir = mkdtempSync(join(tmpdir(), "p11-e2e-"));
  const out = join(dir, `out${ext}`);
  execFileSync("ffmpeg", ["-nostdin", "-v", "error", "-y", ...args, out]);
  return readFileSync(out);
}

const clip = (seconds = 1) =>
  madeByFfmpeg(
    [
      "-f",
      "lavfi",
      "-i",
      `testsrc=size=160x120:rate=10:duration=${seconds}`,
      "-f",
      "lavfi",
      "-i",
      `sine=frequency=440:duration=${seconds}`,
      "-c:v",
      "libx264",
      "-pix_fmt",
      "yuv420p",
      "-c:a",
      "aac",
      "-shortest",
    ],
    ".mp4",
  ); // fmt: skip

const facePhoto = () =>
  madeByFfmpeg(
    ["-f", "lavfi", "-i", "color=c=orange:size=64x64:duration=0.1", "-frames:v", "1"],
    ".png",
  );

test("swaps a face into a clip and produces a playable MP4", async ({ page }) => {
  const foreign = await openStudio(page);
  await page.getByRole("button", { name: "Video" }).click();
  await expect(page.getByRole("note").first()).toHaveText(/Use faces of people who agreed/);

  const form = page.getByRole("form", { name: "Video" });
  await form.getByLabel("Clip").setInputFiles({
    name: "clip.mp4",
    mimeType: "video/mp4",
    buffer: clip(),
  });
  const picker = form.getByRole("group", { name: "Face to swap onto" });
  await expect(picker.getByRole("button", { name: "Face 1" })).toBeVisible();
  await form.getByLabel("Face photo").setInputFiles({
    name: "me.png",
    mimeType: "image/png",
    buffer: facePhoto(),
  });
  await expect(form.getByRole("img", { name: "me.png" })).toBeVisible(); // the upload settled
  await form.getByRole("button", { name: "Swap faces" }).click();
  // The stub pipeline is quick, so the queued state may pass unnoticed: the result is the proof.
  await expect(page.getByRole("button", { name: "Download" })).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".result video")).toBeVisible();
  await expect(page.locator(".progress-label")).toHaveText(/10 frames \(0 kept as they were\)/);
  expect(foreign).toEqual([]);
});

test("the target face is picked on the first frame", async ({ page }) => {
  await openStudio(page);
  await page.getByRole("button", { name: "Video" }).click();
  const form = page.getByRole("form", { name: "Video" });
  await form.getByLabel("Clip").setInputFiles({
    name: "clip.mp4",
    mimeType: "video/mp4",
    buffer: clip(),
  });
  const picker = form.getByRole("group", { name: "Face to swap onto" });
  await expect(form.getByText("Largest face in every frame (P11 follows it).")).toBeVisible();
  await picker.getByRole("button", { name: "Face 1" }).click();
  await expect(form.getByText("Following face 1 across the clip.")).toBeVisible();
  // The face boxes are placed in % of the picker, so it must be exactly the frame's box (17a).
  const frame = (await picker.getByRole("img", { name: "First frame of the clip" }).boundingBox())!;
  const box = (await picker.boundingBox())!;
  for (const k of ["x", "y", "width", "height"] as const)
    expect(
      Math.abs(frame[k] - box[k]),
      `${k}: frame ${frame[k]} vs picker ${box[k]}`,
    ).toBeLessThanOrEqual(1);
});

test("a short clip needs no confirmation, and the frames are kept only on request", async ({
  page,
}) => {
  await openStudio(page);
  await page.getByRole("button", { name: "Video" }).click();
  const form = page.getByRole("form", { name: "Video" });
  await form.getByLabel("Clip").setInputFiles({
    name: "clip.mp4",
    mimeType: "video/mp4",
    buffer: clip(),
  });
  await expect(form.getByRole("group", { name: "Over the recommended limits" })).toHaveCount(0);
  await expect(form.getByLabel(/Keep the frames/)).not.toBeChecked();
});

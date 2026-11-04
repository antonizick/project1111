// v1.0.0 feedback round (Phase 17a): three defects that jsdom cannot see, checked in Chromium.
// (a, b) the mask brush leaves its stroke while drawing, and the live mask equals a replay;
// (c) the Background mask overlay sits exactly on the subject image;
// (d) Face & Pose bounds its pictures and scrolls instead of running off screen.

import { expect, test, type Page } from "@playwright/test";
import { generateButton, openStudio, syntheticPng } from "./studio";

const view = (page: Page, name: string) =>
  page.getByRole("navigation", { name: "Views" }).getByRole("button", { name }).click();

/** Mask alpha at screen points (mapped through the canvas's CSS transform). */
async function alphaAt(page: Page, points: [number, number][]): Promise<number[]> {
  return page.getByTestId("mask-canvas").evaluate((el, pts) => {
    const c = el as HTMLCanvasElement;
    const r = c.getBoundingClientRect();
    const g = c.getContext("2d")!;
    return pts.map(([sx, sy]) => {
      const x = Math.floor(((sx - r.left) * c.width) / r.width);
      const y = Math.floor(((sy - r.top) * c.height) / r.height);
      return g.getImageData(x, y, 1, 1).data[3]!;
    });
  }, points);
}

/** A cheap fingerprint of the whole mask: the sum of alpha weighted by position. */
async function maskHash(page: Page): Promise<number> {
  return page.getByTestId("mask-canvas").evaluate((el) => {
    const c = el as HTMLCanvasElement;
    const d = c.getContext("2d")!.getImageData(0, 0, c.width, c.height).data;
    let h = 0;
    for (let i = 3; i < d.length; i += 4) h = (h + d[i]! * ((i >> 2) % 9973)) % 2147483647;
    return h;
  });
}

async function openInpaint(page: Page) {
  await openStudio(page);
  await view(page, "Inpaint");
  await page
    .getByRole("form", { name: "Inpaint" })
    .getByLabel("Upload photo")
    .setInputFiles({
      name: "synthetic.png",
      mimeType: "image/png",
      buffer: await syntheticPng(page, 1024, 768),
    });
  await expect(page.getByTestId("mask-stage")).toBeVisible();
}

/** Drag across the stage at height `fy` and check the path before and after pointer-up. */
async function dragAndCheck(page: Page, fy: number, expectPainted: boolean) {
  const box = (await page.getByTestId("mask-canvas").boundingBox())!;
  const y = box.y + box.height * fy;
  const xs = [0.25, 0.5, 0.75].map((f) => box.x + box.width * f);
  const path = xs.map((x) => [x, y] as [number, number]);
  await page.mouse.move(box.x + box.width * 0.2, y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.8, y, { steps: 24 });
  const live = await alphaAt(page, path);
  await page.mouse.up();
  const after = await alphaAt(page, path);
  return {
    path,
    live,
    after,
    check: (a: number[]) => a.every((v) => (expectPainted ? v > 0 : v === 0)),
  };
}

for (const [opacity, vw, vh] of [
  [100, 1280, 720],
  [50, 1280, 720],
  [100, 1918, 2130],
  [50, 1918, 2130],
] as const) {
  test(`the brush and eraser leave their stroke while drawing (${opacity} %, ${vw}×${vh})`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: vw, height: vh });
    await openInpaint(page);
    const toolbar = page.getByRole("toolbar", { name: "Mask tools" });
    await toolbar
      .locator("label.slider", { hasText: "Opacity" })
      .locator("input")
      .fill(String(opacity));

    // (a) Brush: the start, middle and end of the path are painted before and after pointer-up.
    const brush = await dragAndCheck(page, 0.5, true);
    expect(brush.check(brush.live), `live alpha ${brush.live}`).toBe(true);
    expect(brush.check(brush.after), `alpha after up ${brush.after}`).toBe(true);
    const second = await dragAndCheck(page, 0.3, true);
    expect(second.check(second.live), `second stroke live ${second.live}`).toBe(true);
    // The first stroke survives the second one.
    const firstStill = await alphaAt(page, brush.path);
    expect(brush.check(firstStill), `first stroke after the second ${firstStill}`).toBe(true);

    // (b) The live mask equals a replay of the history: Undo then Redo changes nothing.
    const live = await maskHash(page);
    await page.getByRole("button", { name: "Undo" }).click();
    await page.getByRole("button", { name: "Redo" }).click();
    expect(await maskHash(page)).toBe(live);

    // Eraser at full opacity clears its whole path while drawing.
    await toolbar.locator("label.slider", { hasText: "Opacity" }).locator("input").fill("100");
    await toolbar.getByRole("button", { name: /Eraser/ }).click();
    const erase = await dragAndCheck(page, 0.5, false);
    expect(erase.check(erase.live), `eraser live ${erase.live}`).toBe(true);
    expect(erase.check(erase.after), `eraser after up ${erase.after}`).toBe(true);
    const erased = await maskHash(page);
    await page.getByRole("button", { name: "Undo" }).click();
    await page.getByRole("button", { name: "Redo" }).click();
    expect(await maskHash(page)).toBe(erased);
  });
}

// 1918×2130 is Nick's real Brave window, 3840×2160 the same monitor maximised (Phase 17e). Photos
// larger than the pane are the common case there; the small ones never hit a size cap.
for (const [vw, vh] of [
  [1280, 720],
  [1920, 1080],
  [1918, 2130],
  [3840, 2160],
] as const) {
  for (const [iw, ih, kind] of [
    [1024, 640, "landscape"],
    [600, 900, "portrait"],
    [3000, 2000, "large landscape"],
    [2000, 3000, "large portrait"],
  ] as const) {
    test(`the Background mask overlay sits on the image (${kind}, ${vw}×${vh})`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: vw, height: vh });
      await openStudio(page);
      await view(page, "Background");
      const form = page.getByRole("form", { name: "Background" });
      await form.getByLabel("Upload photo").setInputFiles({
        name: "subject.png",
        mimeType: "image/png",
        buffer: await syntheticPng(page, iw, ih),
      });
      await expect(form.getByRole("button", { name: "Refine mask" })).toBeEnabled({
        timeout: 15_000,
      });
      const base = page.getByRole("img", { name: "Subject" });
      const overlay = page.locator(".background-overlay");
      await expect(overlay).toBeVisible();
      await expect
        .poll(async () => (await overlay.evaluate((e) => (e as HTMLImageElement).complete)) && 1)
        .toBe(1);
      const a = (await base.boundingBox())!;
      const b = (await overlay.boundingBox())!;
      for (const k of ["x", "y", "width", "height"] as const)
        expect(Math.abs(a[k] - b[k]), `${k}: image ${a[k]} vs overlay ${b[k]}`).toBeLessThanOrEqual(
          1,
        );
      // The toggle hides and restores the overlay without moving it.
      const toggle = form.getByLabel(/mask overlay/i);
      await toggle.uncheck();
      await expect(overlay).toHaveCount(0);
      await toggle.check();
      const c = (await overlay.boundingBox())!;
      expect(Math.abs(c.x - a.x) + Math.abs(c.width - a.width)).toBeLessThanOrEqual(2);
    });
  }
}

for (const [vw, vh] of [
  [1280, 720],
  [1918, 2130],
] as const)
  test(`Face & Pose bounds large pictures and scrolls to every control (${vw}×${vh})`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: vw, height: vh });
    await openStudio(page);
    await view(page, "Face & Pose");
    const big = await syntheticPng(page, 3000, 2000);
    const pane = page.getByRole("region", { name: "Face & Pose" });
    await pane
      .getByLabel("Picture")
      .setInputFiles({ name: "big.png", mimeType: "image/png", buffer: big });
    await pane
      .getByLabel("Face photo")
      .setInputFiles({ name: "big2.png", mimeType: "image/png", buffer: big });
    const thumbs = pane.locator("img.thumb");
    await expect(thumbs).toHaveCount(2);
    for (const t of await thumbs.all()) {
      const b = (await t.boundingBox())!;
      expect(b.height, "thumbnail height").toBeLessThanOrEqual(160);
      expect(b.width, "thumbnail width").toBeLessThan(vw);
    }
    // The pane scrolls itself, and the Run button is reachable.
    const run = pane.getByRole("button", { name: "Swap face" }).last();
    await run.scrollIntoViewIfNeeded();
    await expect(run).toBeInViewport();
    // Nothing runs off the right edge of the page.
    const overflow = await page.evaluate(() => ({
      doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    }));
    expect(overflow.doc).toBeLessThanOrEqual(0);
    const paneBox = (await pane.boundingBox())!;
    expect(paneBox.x + paneBox.width).toBeLessThanOrEqual(vw);

    // The pose editor fits the pane width, and the pane scrolls when it is taller than the window.
    await pane.getByRole("button", { name: "Apply pose" }).first().click();
    const editor = page.getByRole("application", { name: "Pose editor" });
    const eb = (await editor.boundingBox())!;
    expect(eb.x + eb.width).toBeLessThanOrEqual(paneBox.x + paneBox.width + 1);
    const scroll = await pane.evaluate((e) => ({
      sh: e.scrollHeight,
      ch: e.clientHeight,
      overflowY: getComputedStyle(e).overflowY,
    }));
    expect(["auto", "scroll"]).toContain(scroll.overflowY);
    const apply = pane.getByRole("button", { name: "Apply", exact: true });
    await apply.scrollIntoViewIfNeeded();
    await expect(apply).toBeInViewport();
  });

// Sweep (Phase 17a): the other views with the same two classes of defect.
test("Video and Models scroll inside the pane at 1280×720", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await openStudio(page);
  for (const [name, root] of [
    ["Video", ".video-view"],
    ["Models", ".models"],
  ] as const) {
    await view(page, name);
    const pane = page.locator(root);
    const s = await pane.evaluate((e) => getComputedStyle(e).overflowY);
    expect(["auto", "scroll"], `${name} overflow-y`).toContain(s);
    const b = (await pane.boundingBox())!;
    const main = (await page.locator(".main").boundingBox())!;
    expect(b.y + b.height, `${name} bottom`).toBeLessThanOrEqual(main.y + main.height + 1);
  }
  const run = page.getByRole("button", { name: "Swap faces" });
  await view(page, "Video");
  await run.scrollIntoViewIfNeeded();
  await expect(run).toBeInViewport();
});

test("the Text & logo drag area is the preview picture's box", async ({ page }) => {
  await openStudio(page);
  await page.getByLabel("Prompt", { exact: true }).fill("a plain blue poster");
  await generateButton(page).click();
  const result = page.getByRole("region", { name: "Result" });
  await expect(result.getByText("a plain blue poster")).toBeVisible();
  await result.getByRole("button", { name: /Add text/ }).click();
  const dialog = page.getByRole("dialog", { name: "Text & logo" });
  await dialog.getByLabel("Text", { exact: true }).fill("HELLO");
  const img = dialog.getByRole("img", { name: /Text preview/ });
  await expect(img).toBeVisible({ timeout: 15_000 });
  const a = (await img.boundingBox())!;
  const b = (await dialog.getByRole("application", { name: /Drag the text/ }).boundingBox())!;
  for (const k of ["x", "y", "width", "height"] as const)
    expect(Math.abs(a[k] - b[k]), `${k}: image ${a[k]} vs drag area ${b[k]}`).toBeLessThanOrEqual(
      1,
    );
  const d = (await dialog.boundingBox())!;
  expect(a.height).toBeLessThan(d.height);
});

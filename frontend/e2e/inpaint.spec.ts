import { expect, test, type Page } from "@playwright/test";
import { Actions, generateButton, openStudio } from "./studio";

async function apiGet<T>(page: Page, path: string): Promise<T> {
  return page.evaluate(async (p) => {
    const r = await fetch(p, {
      headers: { authorization: `Bearer ${sessionStorage.getItem("p11.token")}` },
    });
    return r.json();
  }, path) as Promise<T>;
}

/** One mask stroke across the canvas centre (a single drag counts as one action). */
async function stroke(page: Page, steps = 12) {
  const box = (await page.getByTestId("mask-stage").boundingBox())!;
  const y = box.y + box.height / 2;
  await page.mouse.move(box.x + box.width * 0.4, y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.6, y + 20, { steps });
  await page.mouse.up();
}

test("inpaint a result in ≤ 4 actions; the mask is image-sized and the child is in the gallery", async ({
  page,
}) => {
  const foreign = await openStudio(page);
  await page.getByLabel("Prompt", { exact: true }).fill("a woman with a blue scarf in a park");
  await generateButton(page).click();
  const result = page.getByRole("region", { name: "Result" });
  await expect(result.getByText("a woman with a blue scarf in a park")).toBeVisible();

  const actions = new Actions(page);
  await actions.click(result.getByRole("button", { name: "Inpaint" })); // 1
  const form = page.getByRole("form", { name: "Inpaint" });
  await expect(form.getByLabel("What should be there (optional)")).toHaveValue(
    "a woman with a blue scarf in a park",
  );
  await expect(form.getByRole("button", { name: "Apply" })).toBeDisabled();
  actions.count += 1; // 2: one mask stroke
  await stroke(page);
  await actions.click(form.getByRole("button", { name: "Apply" })); // 3
  const done = page.getByRole("region", { name: "Inpaint result" });
  await expect(done.getByRole("img", { name: /Inpainted/ })).toBeVisible();
  const download = page.waitForEvent("download");
  await actions.click(done.getByRole("button", { name: "Download" })); // 4
  await download;
  expect(actions.count).toBeLessThanOrEqual(4);
  console.log(`[action-count] inpaint path: ${actions.count}`);

  // The mask went up at the image's resolution, and the result is a child of the original.
  const gallery = await apiGet<{
    items: { id: number; parent_id: number | null; width: number; height: number }[];
  }>(page, "/api/gallery?limit=10");
  const child = gallery.items.find((i) => i.parent_id !== null)!;
  const parent = gallery.items.find((i) => i.id === child.parent_id)!;
  const run = await apiGet<{ bindings: { mask: { ref: string } } }>(
    page,
    `/api/images/${child.id}/recipe`,
  );
  const mask = await apiGet<{ kind: string; width: number; height: number }>(
    page,
    `/api/uploads/${run.bindings.mask.ref}/info`,
  );
  expect(mask).toMatchObject({ kind: "mask", width: parent.width, height: parent.height });
  expect([child.width, child.height]).toEqual([parent.width, parent.height]);

  // Save the inpaint as a template (mask kept) and re-run it with a source image.
  await done.getByRole("button", { name: /Save as Template/ }).click();
  const dialog = page.getByRole("dialog", { name: "Save as Template" });
  await expect(dialog.getByLabel("Keep this mask in the template")).toBeChecked();
  await dialog.getByLabel("Template name").fill("Scarf fix e2e");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Saved template “Scarf fix e2e”.")).toBeVisible();
  const templates = await apiGet<{ name: string; slots: { name: string }[] }[]>(
    page,
    "/api/templates?q=Scarf",
  );
  expect(templates.find((t) => t.name === "Scarf fix e2e")!.slots.map((s) => s.name)).toEqual([
    "source",
  ]);
  expect(foreign).toEqual([]);
});

test("mask editor keeps up on a 2560×1440 photo (draw time per pointer move)", async ({ page }) => {
  await openStudio(page);
  await page
    .getByRole("navigation", { name: "Views" })
    .getByRole("button", { name: "Inpaint" })
    .click();
  // A synthetic 2560x1440 photo made in the page (no files in the repo; S6).
  const b64 = await page.evaluate(async () => {
    const c = document.createElement("canvas");
    c.width = 2560;
    c.height = 1440;
    const g = c.getContext("2d")!;
    const grad = g.createLinearGradient(0, 0, 2560, 1440);
    grad.addColorStop(0, "#245");
    grad.addColorStop(1, "#c96");
    g.fillStyle = grad;
    g.fillRect(0, 0, 2560, 1440);
    const blob = await new Promise<Blob>((r) => c.toBlob((b) => r(b!), "image/png"));
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let s = "";
    for (const x of bytes) s += String.fromCharCode(x);
    return btoa(s);
  });
  await page.getByLabel("Upload photo").setInputFiles({
    name: "synthetic.png",
    mimeType: "image/png",
    buffer: Buffer.from(b64, "base64"),
  });
  const stage = page.getByTestId("mask-stage");
  await expect(stage).toBeVisible();
  // Frame intervals while painting a long stroke with a big brush.
  await page.keyboard.press("]");
  await page.keyboard.press("]");
  await page.evaluate(() => {
    const w = window as unknown as { __frames: number[]; __run: boolean };
    w.__frames = [];
    w.__run = true;
    let last = performance.now();
    const tick = (t: number) => {
      w.__frames.push(t - last);
      last = t;
      if (w.__run) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
  await stroke(page, 240);
  const frames = await page.evaluate(() => {
    const w = window as unknown as { __frames: number[]; __run: boolean };
    w.__run = false;
    return w.__frames.slice(1);
  });
  const avg = Number(await stage.getAttribute("data-draw-avg-ms"));
  const max = Number(await stage.getAttribute("data-draw-max-ms"));
  const moves = Number(await stage.getAttribute("data-draw-moves"));
  const sorted = [...frames].sort((a, b) => a - b);
  const p95 = sorted[Math.floor(sorted.length * 0.95)] ?? 0;
  console.log(
    `[frame-timing] 2560x1440: ${moves} moves, draw avg ${avg.toFixed(2)} ms, max ${max.toFixed(2)} ms; ` +
      `${frames.length} frames, median ${sorted[Math.floor(sorted.length / 2)]?.toFixed(1)} ms, p95 ${p95.toFixed(1)} ms`,
  );
  expect(moves).toBeGreaterThan(100);
  // 60 fps leaves 16.7 ms per frame; drawing a move must take a small part of it.
  expect(avg).toBeLessThan(8);
  await expect(page.getByRole("button", { name: "Undo" })).toBeEnabled();
  await page.keyboard.press("Control+z");
  await expect(page.getByRole("button", { name: "Undo" })).toBeDisabled();
  await page.keyboard.press("Control+Shift+z");
  await expect(page.getByRole("button", { name: "Undo" })).toBeEnabled();
});

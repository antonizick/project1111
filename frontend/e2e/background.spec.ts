// Background replacement (Phase 11): the Appendix B daily path -- open a result, Background,
// choose photo, Apply, Download -- in ≤ 5 actions. Runs against `p11 serve --fake`, so the
// segmenter is the deterministic stub; the real model's path is `tests/gpu/` and the laptop
// acceptance run. File-picker interactions count as one action (the convention of
// inpaint.spec.ts: "selecting a file in the file picker counts as one action").

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

/** A synthetic photo made in the page (no files in the repo; S6). */
async function syntheticPng(page: Page, w: number, h: number, a: string, b: string) {
  const b64 = await page.evaluate(
    ([w, h, a, b]) => {
      const c = document.createElement("canvas");
      c.width = w;
      c.height = h;
      const g = c.getContext("2d")!;
      const grad = g.createLinearGradient(0, 0, w, h);
      grad.addColorStop(0, a);
      grad.addColorStop(1, b);
      g.fillStyle = grad;
      g.fillRect(0, 0, w, h);
      return new Promise<string>((resolve) =>
        c.toBlob(async (blob) => {
          const bytes = new Uint8Array(await blob!.arrayBuffer());
          let s = "";
          for (const x of bytes) s += String.fromCharCode(x);
          resolve(btoa(s));
        }, "image/png"),
      );
    },
    [w, h, a, b] as const,
  );
  return Buffer.from(b64, "base64");
}

test("replace a background in ≤ 5 actions; the result is a child with mask + photo inputs", async ({
  page,
}) => {
  const foreign = await openStudio(page);
  await page.getByLabel("Prompt", { exact: true }).fill("a red ceramic mug on a wooden table");
  await generateButton(page).click();
  const result = page.getByRole("region", { name: "Result" });
  await expect(result.getByText("a red ceramic mug on a wooden table")).toBeVisible();

  const actions = new Actions(page);
  await actions.click(result.getByRole("button", { name: "Background" })); // 1
  const form = page.getByRole("form", { name: "Background" });
  await expect(form.getByRole("button", { name: "Refine mask" })).toBeEnabled({
    timeout: 15_000,
  });

  actions.count += 1; // 2: choose the background photo (file picker)
  await form.getByLabel("Background photo").setInputFiles({
    name: "studio.png",
    mimeType: "image/png",
    buffer: await syntheticPng(page, 640, 480, "#284", "#746"),
  });
  await actions.click(form.getByRole("button", { name: "Replace Background" })); // 3
  const done = page.getByRole("region", { name: "Background result" });
  // The first background job of a run also warms up the engine and segmenter (cold start).
  await expect(done.getByRole("img", { name: /New background/ })).toBeVisible({ timeout: 20_000 });
  const download = page.waitForEvent("download");
  await actions.click(done.getByRole("button", { name: "Download" })); // 4
  await download;
  expect(actions.count).toBeLessThanOrEqual(5);
  console.log(`[action-count] background path: ${actions.count}`);

  // The result keeps the subject's size and is its child in the gallery; the run records the
  // subject mask and the background photo as inputs (neither is stored in the recipe).
  const gallery = await apiGet<{
    items: { id: number; parent_id: number | null; width: number; height: number }[];
  }>(page, "/api/gallery?limit=10");
  const child = gallery.items.find((i) => i.parent_id !== null)!;
  const parent = gallery.items.find((i) => i.id === child.parent_id)!;
  expect([child.width, child.height]).toEqual([parent.width, parent.height]);
  const run = await apiGet<{ bindings: Record<string, { ref: string }> }>(
    page,
    `/api/images/${child.id}/recipe`,
  );
  expect(run.bindings.mask).toBeTruthy();
  expect(run.bindings.background).toBeTruthy();
  const mask = await apiGet<{ kind: string; width: number; height: number }>(
    page,
    `/api/uploads/${run.bindings.mask!.ref}/info`,
  );
  expect(mask).toMatchObject({ kind: "mask", width: parent.width, height: parent.height });

  // Save as Template: a background run re-segments each run's subject by default, so the
  // template asks only for the source and the background photo.
  await done.getByRole("button", { name: /Save as Template/ }).click();
  const dialog = page.getByRole("dialog", { name: "Save as Template" });
  await expect(dialog.getByLabel("Find the subject each time")).toBeChecked();
  await dialog.getByLabel("Template name").fill("Mug on studio e2e");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Saved template “Mug on studio e2e”.")).toBeVisible();
  const templates = await apiGet<{ name: string; slots: { name: string }[] }[]>(
    page,
    "/api/templates?q=Mug",
  );
  expect(templates.find((t) => t.name === "Mug on studio e2e")!.slots.map((s) => s.name)).toEqual([
    "background",
    "source",
  ]);
  expect(foreign).toEqual([]);
});

test("Refine opens the mask editor seeded with the auto-mask", async ({ page }) => {
  await openStudio(page);
  await page
    .getByRole("navigation", { name: "Views" })
    .getByRole("button", { name: "Background" })
    .click();
  const form = page.getByRole("form", { name: "Background" });
  await form.getByLabel("Upload photo").setInputFiles({
    name: "subject.png",
    mimeType: "image/png",
    buffer: await syntheticPng(page, 512, 384, "#631", "#a85"),
  });
  await expect(form.getByRole("button", { name: "Refine mask" })).toBeEnabled({
    timeout: 15_000,
  });
  await form.getByRole("button", { name: "Refine mask" }).click();
  const stage = page.getByTestId("mask-stage");
  await expect(stage).toBeVisible();
  // The auto-mask is the editor's first entry, so it can be accepted without painting.
  const useMask = page.getByRole("button", { name: "Use this mask" });
  await expect(useMask).toBeEnabled();
  await useMask.click();
  await expect(form.getByRole("button", { name: "Replace Background" })).toBeDisabled();
  // No background chosen yet; the button enables once one is picked.
  await form.getByRole("button", { name: "Colour / transparent" }).click();
  await expect(form.getByRole("button", { name: "Replace Background" })).toBeEnabled();
});

test("Describe generates a background and the subject lands on it", async ({ page }) => {
  await openStudio(page);
  await page
    .getByRole("navigation", { name: "Views" })
    .getByRole("button", { name: "Background" })
    .click();
  const form = page.getByRole("form", { name: "Background" });
  await form.getByLabel("Upload photo").setInputFiles({
    name: "subject.png",
    mimeType: "image/png",
    buffer: await syntheticPng(page, 512, 384, "#631", "#a85"),
  });
  await expect(form.getByRole("button", { name: "Refine mask" })).toBeEnabled({
    timeout: 15_000,
  });
  await form.getByLabel("Describe the background").fill("a sunny beach");
  await form.getByRole("button", { name: "Generate" }).click();
  await expect(form.getByRole("img", { name: "Background" })).toBeVisible({ timeout: 30_000 });
  await form.getByRole("button", { name: "Replace Background" }).click();
  const done = page.getByRole("region", { name: "Background result" });
  await expect(done.getByRole("img", { name: /New background/ })).toBeVisible();
});

// Face & Pose (Phase 12): the four tools open, the consent notice is on the swap panel, and the
// pose editor really edits a skeleton. Runs against `p11 serve --fake`, so the face tools are the
// deterministic stubs; the real models run in `tests/gpu/` and the laptop acceptance run.

import { expect, test } from "@playwright/test";
import { openStudio } from "./studio";

test("the Face & Pose view opens with its four tools", async ({ page }) => {
  const foreign = await openStudio(page);
  await page.getByRole("button", { name: "Face & Pose" }).click();
  await expect(page.getByRole("button", { name: "Swap face" }).first()).toBeVisible();
  for (const tool of ["Swap face", "Apply pose", "Use as reference", "Restore faces"]) {
    await expect(page.getByRole("button", { name: tool }).first()).toBeVisible();
  }
  expect(foreign).toEqual([]);
});

test("the swap panel carries the consent notice", async ({ page }) => {
  await openStudio(page);
  await page.getByRole("button", { name: "Face & Pose" }).click();
  await expect(page.getByRole("note")).toHaveText(/Use faces of people who agreed/);
});

test("the pose editor draws a skeleton and can mirror it", async ({ page }) => {
  await openStudio(page);
  await page.getByRole("button", { name: "Face & Pose" }).click();
  await page.getByRole("button", { name: "Apply pose" }).first().click();
  const editor = page.getByRole("application", { name: "Pose editor" });
  await expect(editor).toBeVisible();
  // Joints and limbs are drawn as circles and lines on black.
  await expect(editor.locator("circle")).toHaveCount(18);
  await expect(editor.locator("line").first()).toBeVisible();

  await page.getByLabel("Stock pose").selectOption("waving");
  await expect(editor.locator("circle")).toHaveCount(18);
  const before = await editor.locator("circle").nth(4).getAttribute("cx");

  await page.getByRole("button", { name: "Mirror" }).click();
  const after = await editor.locator("circle").nth(4).getAttribute("cx");
  expect(after).not.toBe(before);
});

test("the reference tool keeps style or character", async ({ page }) => {
  await openStudio(page);
  await page.getByRole("button", { name: "Face & Pose" }).click();
  await page.getByRole("button", { name: "Use as reference" }).first().click();
  await expect(page.getByLabel("What to keep")).toBeVisible();
  await page.getByLabel("What to keep").selectOption("character");
  await expect(page.getByLabel("What to keep")).toHaveValue("character");
});

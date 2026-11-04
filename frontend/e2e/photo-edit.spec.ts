// Start from a photo (Phase 17b, ADR-0038) on the FakeEngine, in Chromium: upload → prompt →
// Light touch → Generate lands a result in the gallery in a handful of actions, the photo's
// thumbnail stays bounded (17a layout rule), and a result can be reused as the starting photo.

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { Actions, generateButton, openStudio, syntheticPng } from "./studio";

for (const [vw, vh] of [
  [1280, 720],
  [1918, 2130],
] as const)
  test(`photo edit: upload, prompt, Light touch, Generate, ≤ 5 actions (${vw}×${vh})`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: vw, height: vh });
    const foreign = await openStudio(page);
    const act = new Actions(page);
    const form = page.getByRole("form", { name: "Generate" });
    const photo = await syntheticPng(page, 2400, 1600);
    act.count += 1; // choosing the file is one action
    await form
      .getByLabel("Start from a photo (optional)")
      .setInputFiles({ name: "room.png", mimeType: "image/png", buffer: photo });
    const thumb = form.getByAltText("Starting photo");
    await expect(thumb).toBeVisible();
    const b = (await thumb.boundingBox())!;
    expect(b.height, "thumbnail height").toBeLessThanOrEqual(160);
    await expect(form.getByRole("button", { name: "Square 1024" })).toBeDisabled();
    // The photo controls (thumbnail, Remove, Strength chips) pass axe and are keyboard reachable.
    const axe = await new AxeBuilder({ page }).include("form[aria-label='Generate']").analyze();
    expect(axe.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
    await form.getByRole("button", { name: "Remove photo" }).focus();
    await page.keyboard.press("Tab");
    await expect(form.getByRole("button", { name: "Light touch" })).toBeFocused();
    await form.getByLabel("Prompt").fill("a modern furnished living room, sofa, rug, plants");
    await act.click(form.getByRole("button", { name: "Light touch" }));
    await act.click(generateButton(page));
    const result = page.getByRole("region", { name: "Result" });
    await expect(result.getByRole("button", { name: "Use as starting photo" })).toBeVisible({
      timeout: 30_000,
    });
    // 2400 x 1600 (3:2) → the 1216 x 832 bucket, then the model chain toward the photo's size.
    await expect(result.getByText(/\d+ × \d+/)).toBeVisible();
    expect(act.count).toBeLessThanOrEqual(5);
    // Nothing runs off the right edge.
    const over = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(over).toBeLessThanOrEqual(0);

    // The result goes back in as the next starting photo.
    await result.getByRole("button", { name: "Use as starting photo" }).click();
    await expect(form.getByAltText("Starting photo")).toHaveAttribute("src", /\/api\/images\/\d+/);
    await form.getByRole("button", { name: "Remove photo" }).click();
    await expect(form.getByRole("button", { name: "Square 1024" })).toBeEnabled();
    expect(foreign).toEqual([]);
  });

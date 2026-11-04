// Phase 17g on the FakeEngine: Small and Medium thumbnails at the laptop's and Nick's window sizes,
// and From gallery end to end on Generate, Inpaint and Face, sending references and no upload
// (ADR-0046).

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { generateButton, openStudio, syntheticPng } from "./studio";

async function makeImage(page: Page, prompt: string) {
  const form = page.getByRole("form", { name: "Generate" });
  await form.getByLabel("Prompt").fill(prompt);
  await generateButton(page).click();
  await expect(page.getByRole("region", { name: "Result" }).getByRole("img").first()).toBeVisible({
    timeout: 30_000,
  });
}

function countUploads(page: Page) {
  const seen = { uploads: 0 };
  page.on("request", (r) => {
    if (r.method() === "POST" && new URL(r.url()).pathname === "/api/uploads") seen.uploads += 1;
  });
  return seen;
}

async function pick(page: Page, label: string, alt: string) {
  await page.getByRole("button", { name: `From gallery for ${label}` }).click();
  const dialog = page.getByRole("dialog", { name: "choose from the gallery" });
  await dialog.getByRole("button", { name: alt }).first().click();
  await expect(dialog).toBeHidden();
}

const view = (page: Page, name: string) =>
  page.getByRole("navigation", { name: "Views" }).getByText(name, { exact: true });

for (const [vw, vh] of [
  [1280, 720],
  [1918, 2130],
] as const)
  test(`gallery thumbnails: Small and Medium fit at ${vw}×${vh}`, async ({ page }) => {
    await page.setViewportSize({ width: vw, height: vh });
    await openStudio(page);
    await makeImage(page, "a size check");
    await makeImage(page, "a second size check");
    await view(page, "Gallery").click();
    const tiles = page.getByRole("group", { name: "Images" }).getByRole("listitem");
    await expect(tiles.first()).toBeVisible();
    const size = page.getByRole("group", { name: "Thumbnail size" });
    const width = async () => (await tiles.first().boundingBox())!.width;
    const noOverflow = async () =>
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        vw,
      );
    await size.getByRole("button", { name: "Medium" }).click();
    expect(await width()).toBeCloseTo(200, 0);
    await noOverflow();
    await size.getByRole("button", { name: "Small" }).click();
    expect(await width()).toBeCloseTo(120, 0);
    const second = (await tiles.nth(1).boundingBox())!;
    const first = (await tiles.first().boundingBox())!;
    expect(second.x - first.x).toBeCloseTo(128, 0);
    await noOverflow();
    await page.reload();
    await expect(page.getByText(/Connected · v/)).toBeVisible();
    await view(page, "Gallery").click();
    await expect(tiles.first()).toBeVisible();
    expect(await width()).toBeCloseTo(120, 0);
    await page.getByRole("group", { name: "Thumbnail size" }).getByText("Medium").click();
  });

test("From gallery: Generate, Inpaint and Face send references, never an upload", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const foreign = await openStudio(page);
  await makeImage(page, "a picker fox");
  const seen = countUploads(page);

  // Generate: the picked image becomes the starting photo.
  const form = page.getByRole("form", { name: "Generate" });
  await form.getByRole("button", { name: "From gallery for Start from a photo" }).click();
  const dialog = page.getByRole("dialog", { name: "choose from the gallery" });
  await expect(dialog.getByRole("button", { name: "a picker fox" }).first()).toBeVisible();
  const axe = await new AxeBuilder({ page }).include("[role=dialog]").analyze();
  expect(axe.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await pick(page, "Start from a photo", "a picker fox");
  await expect(form.getByAltText("Starting photo")).toBeVisible();
  const sent = page.waitForRequest(
    (r) => r.method() === "POST" && new URL(r.url()).pathname === "/api/jobs",
  );
  await generateButton(page).click();
  const body = (await sent).postDataJSON();
  expect(body.recipe.source_image.ref).toMatch(/^gallery\/\d+$/);
  expect(body.parent).toEqual(expect.any(Number));

  // Inpaint: fresh form has the crop off; the picked image opens in the editor.
  await view(page, "Inpaint").click();
  await expect(page.getByLabel("Only masked area at full resolution")).not.toBeChecked();
  await pick(page, "Upload photo", "a picker fox");
  await expect(page.getByRole("button", { name: "Apply" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Fix or change part/ })).toBeHidden();

  // Face: Picture and Face photo from the gallery run a swap.
  await page.getByRole("navigation", { name: "Views" }).getByText(/^Face/).click();
  await pick(page, "Picture", "a picker fox");
  await pick(page, "Face photo", "a picker fox");
  const swap = page.waitForRequest(
    (r) => r.method() === "POST" && new URL(r.url()).pathname === "/api/jobs",
  );
  await page.getByRole("button", { name: "Swap face" }).last().click();
  const swapped = (await swap).postDataJSON();
  expect(swapped.recipe.source_image.ref).toMatch(/^gallery\/\d+$/);
  expect(swapped.bindings.face.ref).toMatch(/^gallery\/\d+$/);

  expect(seen.uploads, "picking uploads nothing").toBe(0);
  expect(foreign).toEqual([]);
});

test("a file can still be chosen beside From gallery", async ({ page }) => {
  await openStudio(page);
  const form = page.getByRole("form", { name: "Generate" });
  await expect(form.getByRole("button", { name: /From gallery/ })).toBeVisible();
  const photo = await syntheticPng(page, 800, 600);
  await form
    .getByLabel("Start from a photo (optional)")
    .setInputFiles({ name: "room.png", mimeType: "image/png", buffer: photo });
  await expect(form.getByAltText("Starting photo")).toBeVisible();
});

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

/** The job a press of `go` submits, followed until it finishes; returns its request body. */
async function runJob(page: Page, go: () => Promise<void>) {
  const sent = page.waitForResponse(
    (r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/jobs",
  );
  await go();
  const response = await sent;
  const { id } = (await response.json()) as { id: string };
  await expect
    .poll(
      () =>
        page.evaluate(async (jobId) => {
          const r = await fetch(`/api/jobs/${jobId}`, {
            headers: { authorization: `Bearer ${sessionStorage.getItem("p11.token")}` },
          });
          return ((await r.json()) as { state: string }).state;
        }, id),
      { timeout: 20_000 },
    )
    .toBe("done");
  return response.request().postDataJSON();
}

async function stroke(page: Page) {
  const box = (await page.getByTestId("mask-stage").boundingBox())!;
  const y = box.y + box.height / 2;
  await page.mouse.move(box.x + box.width * 0.4, y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.6, y + 20, { steps: 12 });
  await page.mouse.up();
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

test("From gallery: picked images run jobs on Generate, Inpaint, Background and Face, by reference", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1280, height: 900 });
  const foreign = await openStudio(page);
  await makeImage(page, "a picker fox");
  const seen = countUploads(page);
  const gallery = /^gallery\/\d+$/;

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
  const body = await runJob(page, () => generateButton(page).click());
  expect(body.recipe.source_image.ref).toMatch(gallery);
  expect(body.parent).toEqual(expect.any(Number));
  expect(seen.uploads, "Generate uploads nothing").toBe(0);

  // Inpaint: fresh form has the crop off; the picked image opens in the editor.
  await view(page, "Inpaint").click();
  await expect(page.getByLabel("Only masked area at full resolution")).not.toBeChecked();
  await pick(page, "Upload photo", "a picker fox");
  await expect(page.getByRole("button", { name: "Apply" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Fix or change part/ })).toBeHidden();
  expect(seen.uploads, "picking uploads nothing").toBe(0);
  await stroke(page);
  const inpaint = await runJob(page, () => page.getByRole("button", { name: "Apply" }).click());
  expect(inpaint.recipe.source_image.ref).toMatch(gallery);
  expect(inpaint.recipe.steps[0].crop).toBe(false);
  seen.uploads = 0; // the painted mask is the one upload Apply makes

  // Background: subject and background photo both from the gallery (the auto-mask uploads).
  await view(page, "Background").click();
  await pick(page, "Upload photo", "a picker fox");
  await pick(page, "Background photo", "a picker fox");
  await expect(page.getByAltText("Background", { exact: true })).toBeVisible();
  const replace = page.getByRole("button", { name: "Replace Background" });
  await expect(replace).toBeEnabled();
  const background = await runJob(page, () => replace.click());
  expect(background.recipe.source_image.ref).toMatch(gallery);
  expect(background.bindings.background.ref).toMatch(gallery);
  seen.uploads = 0;

  // Face: Picture and Face photo from the gallery run a swap.
  await page.getByRole("navigation", { name: "Views" }).getByText(/^Face/).click();
  await pick(page, "Picture", "a picker fox");
  await pick(page, "Face photo", "a picker fox");
  const swapped = await runJob(page, () =>
    page.getByRole("button", { name: "Swap face" }).last().click(),
  );
  expect(swapped.recipe.source_image.ref).toMatch(gallery);
  expect(swapped.bindings.face.ref).toMatch(gallery);

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

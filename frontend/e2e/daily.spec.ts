import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { Actions, generateButton, openStudio } from "./studio";

// The daily path on the FakeEngine (`p11 serve --fake`, ~50 ms per sampler step).
test("typed prompt → Generate → Download takes ≤ 3 actions and strips metadata", async ({
  page,
}) => {
  const foreign = await openStudio(page);
  const actions = new Actions(page);
  await page.getByLabel("Prompt", { exact: true }).fill("a lighthouse on a rocky coast at dusk");
  await actions.press("Control+Enter");
  const result = page.getByRole("region", { name: "Result" });
  await expect(result.getByText("a lighthouse on a rocky coast at dusk")).toBeVisible();
  const download = page.waitForEvent("download");
  await actions.click(result.getByRole("button", { name: "Download" }));
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^p11-\d+\.png$/);
  const bytes = readFileSync((await file.path())!);
  expect(bytes.subarray(1, 4).toString()).toBe("PNG");
  expect(bytes.includes(Buffer.from("p11:recipe"))).toBe(false);
  expect(actions.count).toBeLessThanOrEqual(3);
  console.log(`[action-count] generate→download: ${actions.count}`);
  await expect(page.getByText(/^Model: realvisxl5-lightning$/)).toBeVisible();
  expect(foreign).toEqual([]);
});

test("Esc cancels a running batch", async ({ page }) => {
  const foreign = await openStudio(page);
  await page
    .getByLabel("Prompt", { exact: true })
    .fill("snow-capped mountains above a misty valley");
  await page.getByLabel("Number of images").fill("4");
  await page.getByRole("button", { name: "▸ Advanced" }).click();
  await page.getByLabel("Steps", { exact: true }).fill("60"); // ~3 s per image on the fake engine
  await generateButton(page).click();
  await expect(page.getByText(/Generating · /)).toBeVisible();
  await page.getByLabel("Prompt", { exact: true }).focus();
  await page.keyboard.press("Escape");
  await expect(generateButton(page)).toBeVisible();
  await expect(page.getByRole("region", { name: "Progress" })).toHaveCount(0);
  expect(foreign).toEqual([]);
});

test("variations from the result (V) land in the gallery, which searches and compares", async ({
  page,
}) => {
  const foreign = await openStudio(page);
  await page.getByLabel("Prompt", { exact: true }).fill("a quiet harbour with wooden boats");
  await generateButton(page).click();
  const result = page.getByRole("region", { name: "Result" });
  await expect(result.getByText("a quiet harbour with wooden boats")).toBeVisible();
  await page.getByLabel("Prompt", { exact: true }).blur();
  await page.keyboard.press("v");
  await expect(page.getByRole("region", { name: "Progress" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Progress" })).toHaveCount(0);

  await page.keyboard.press("g");
  await page.getByLabel("Search prompts").fill("harb");
  const tiles = page.getByRole("group", { name: "Images" }).getByRole("listitem");
  await expect(tiles).toHaveCount(2);
  await page
    .getByLabel(/^Select image/)
    .first()
    .check();
  await page
    .getByLabel(/^Select image/)
    .nth(1)
    .check();
  await page.getByRole("button", { name: "Compare" }).click();
  const compare = page.getByRole("dialog", { name: "Compare 2 images" });
  await compare.getByRole("button", { name: "Zoom in" }).click();
  await expect(compare.getByRole("img", { name: /zoom 125 %/ })).toHaveCount(2);
  await page.keyboard.press("Escape");

  const zip = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export 2" }).click();
  const file = await zip;
  expect(file.suggestedFilename()).toBe("p11-export.zip");
  const bytes = readFileSync((await file.path())!);
  expect(bytes.subarray(0, 2).toString()).toBe("PK");
  expect(bytes.includes(Buffer.from("p11:recipe"))).toBe(false);

  await page
    .getByRole("button", { name: /^Open: a quiet harbour/ })
    .first()
    .click();
  await page.getByRole("button", { name: "Open as recipe" }).click();
  await expect(page.getByLabel("Prompt", { exact: true })).toHaveValue(/a quiet harbour/);
  await expect(page.getByLabel("Lock seed")).toBeChecked();
  expect(foreign).toEqual([]);
});

test("Generate and Gallery pass axe accessibility checks", async ({ page }) => {
  await openStudio(page);
  const generate = await new AxeBuilder({ page }).analyze();
  expect(generate.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  await page.getByRole("button", { name: "Gallery" }).click();
  await expect(page.getByRole("group", { name: "Images" })).toBeVisible();
  const gallery = await new AxeBuilder({ page }).analyze();
  expect(gallery.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
});

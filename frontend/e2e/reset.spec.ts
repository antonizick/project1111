// Phase 17h on the FakeEngine: Reset clears the tabs without a single writing request, an old
// hand-off does not come back, and it waits for a running job (ADR-0048).

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { generateButton, openStudio } from "./studio";

const view = (page: Page, name: string) =>
  page.getByRole("navigation", { name: "Views" }).getByRole("button", { name }).click();

const openDialog = async (page: Page) => {
  await page.getByRole("button", { name: "Reset Studio: clear all tabs" }).click();
  return page.getByRole("dialog", { name: "Reset Studio?" });
};

function writes(page: Page) {
  const sent: string[] = [];
  page.on("request", (r) => {
    if (r.method() !== "GET" && r.method() !== "HEAD") sent.push(`${r.method()} ${r.url()}`);
  });
  return sent;
}

test("clears every tab on the same tab, sends no write, and old work stays gone", async ({
  page,
}) => {
  const foreign = await openStudio(page);
  const prompt = page.getByLabel("Prompt", { exact: true });
  await prompt.fill("a lighthouse at dusk");
  await generateButton(page).click();
  const result = page.getByRole("region", { name: "Result" });
  await expect(result.getByRole("img").first()).toBeVisible({ timeout: 30_000 });
  await result.getByRole("button", { name: "Inpaint", exact: true }).click();
  await expect(page.getByTestId("mask-stage")).toBeVisible();
  await view(page, "Gallery");
  await page.getByLabel("Search prompts").fill("lighthouse");
  await view(page, "Inpaint");

  const sent = writes(page);
  const dialog = await openDialog(page);
  await dialog.getByRole("button", { name: "Reset", exact: true }).click();
  await expect(page.getByText("Studio reset. Nothing on disk changed.")).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Views" }).getByRole("button", { name: "Inpaint" }),
  ).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("mask-stage")).toHaveCount(0);

  await view(page, "Generate");
  await expect(prompt).toHaveValue("");
  await expect(page.getByRole("region", { name: "Result" }).getByRole("img")).toHaveCount(0);
  await expect(page.getByText(/^Model: style default$/)).toBeVisible();
  await view(page, "Gallery");
  await expect(page.getByLabel("Search prompts")).toHaveValue("");
  await expect(page.locator(".tile-row").first()).toBeVisible();
  expect(sent).toEqual([]);
  expect(foreign).toEqual([]);
});

test("waits for a running job, which stays cancellable", async ({ page }) => {
  await openStudio(page);
  await page.getByLabel("Prompt", { exact: true }).fill("snow on a quiet mountain");
  await page.getByLabel("Number of images").fill("4");
  await page.getByRole("button", { name: "▸ Advanced" }).click();
  await page.getByLabel("Steps", { exact: true }).fill("60");
  await generateButton(page).click();
  await expect(page.getByRole("region", { name: "Progress" })).toBeVisible();

  const dialog = await openDialog(page);
  await expect(dialog.getByText(/still running/)).toBeVisible();
  const reset = dialog.getByRole("button", { name: "Reset", exact: true });
  await expect(reset).toBeDisabled();
  await dialog.getByRole("button", { name: "Cancel" }).click();

  await page.keyboard.press("Escape"); // the view still holds the job
  await expect(page.getByRole("region", { name: "Progress" })).toHaveCount(0);
  await openDialog(page);
  await expect(reset).toBeEnabled();
  await reset.click();
  await expect(page.getByLabel("Prompt", { exact: true })).toHaveValue("");
});

for (const [width, height] of [
  [1280, 720],
  [1918, 2130],
] as const)
  test(`sits at the right of the top bar at ${width}×${height}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await openStudio(page);
    const bar = page.locator(".topbar");
    expect(await bar.evaluate((b) => b.scrollWidth <= b.clientWidth)).toBe(true);
    const barBox = (await bar.boundingBox())!;
    const box = (await page
      .getByRole("button", { name: "Reset Studio: clear all tabs" })
      .boundingBox())!;
    expect(barBox.x + barBox.width - (box.x + box.width)).toBeLessThanOrEqual(20);
    await openDialog(page);
    const axe = await new AxeBuilder({ page }).include(".dialog").analyze();
    expect(axe.violations).toEqual([]);
  });

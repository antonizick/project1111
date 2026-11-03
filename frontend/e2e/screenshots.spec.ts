import { expect, test } from "@playwright/test";
import { generateButton, openStudio } from "./studio";

// Documentation screenshots (docs/images/), FakeEngine images only. Run with P11_SCREENSHOTS=1.
test.skip(!process.env.P11_SCREENSHOTS, "set P11_SCREENSHOTS=1 to refresh docs/images");
test.use({ viewport: { width: 1440, height: 900 } });

test("screenshots", async ({ page }) => {
  await openStudio(page);
  await page.getByLabel("Prompt", { exact: true }).fill("a lighthouse on a rocky coast at dusk");
  await generateButton(page).click();
  await expect(page.getByRole("region", { name: "Result" })).toBeVisible();
  await page.screenshot({ path: "../docs/images/p11-generate.png" });
  await page.getByRole("button", { name: "Gallery" }).click();
  await expect(
    page.getByRole("group", { name: "Images" }).getByRole("listitem").first(),
  ).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: "../docs/images/p11-gallery.png" });
  const boxes = page.getByLabel(/^Select image/);
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  await page.getByRole("button", { name: "Compare" }).click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: "../docs/images/p11-compare.png" });
});

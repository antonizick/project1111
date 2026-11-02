import { expect, test } from "@playwright/test";

test("placeholder page reports a healthy service", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "P11 Studio" })).toBeVisible();
  await expect(page.getByText(/Service is ok/)).toBeVisible();
});

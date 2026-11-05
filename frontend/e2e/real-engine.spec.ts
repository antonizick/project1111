import { expect, test } from "@playwright/test";

// Manual laptop check with the real engine (Phase 08 acceptance). Start a real `p11 serve`, mint
// a link with `p11 open --print-url` and pass it in P11_REAL_LAUNCH_URL; skipped otherwise.
const url = process.env.P11_REAL_LAUNCH_URL;
test.skip(!url, "set P11_REAL_LAUNCH_URL to run against a real-engine Studio");
test.setTimeout(240_000);

test("1920×1080 photoreal from Simple mode with Ctrl+Enter on the real engine", async ({
  page,
}) => {
  await page.goto(url!);
  await expect(page.getByText(/Connected · v/)).toBeVisible();
  await page.getByLabel("Prompt", { exact: true }).fill("a lighthouse on a rocky coast at dusk");
  await expect(page.getByRole("button", { name: "Wallpaper 1920 x 1080 (16:9)" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  const started = Date.now();
  await page.keyboard.press("Control+Enter");
  await expect(page.getByText(/VRAM \d+\.\d \/ \d+\.\d GB/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/^\d+ °C/)).toBeVisible();
  const result = page.getByRole("region", { name: "Result" });
  await expect(result.getByText("1920 × 1080")).toBeVisible({ timeout: 200_000 });
  console.log(`[real-engine] first image in ${((Date.now() - started) / 1000).toFixed(1)} s`);
  console.log(
    `[real-engine] status: ${await page.getByRole("contentinfo", { name: "Status" }).innerText()}`,
  );
  await page.screenshot({ path: "test-results/real-engine-result.png" });
  await page.getByRole("button", { name: "Gallery", exact: true }).click();
  await expect(page.getByRole("button", { name: /^Open: a lighthouse/ })).toBeVisible();
});

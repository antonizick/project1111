import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { generateButton, openStudio } from "./studio";

// Phase 16 accessibility pass: axe (WCAG 2.1 A/AA, contrast included) on every view in both
// themes with reduced motion requested, plus a keyboard-only walkthrough of the daily path.
const VIEWS = [
  "Generate",
  "Gallery",
  "Templates",
  "Inpaint",
  "Background",
  "Face & Pose",
  "Video",
  "Models",
] as const;

test.use({ reducedMotion: "reduce" });

for (const theme of ["light", "dark"] as const) {
  test(`every view passes axe in the ${theme} theme`, async ({ page }) => {
    const foreign = await openStudio(page);
    const toggle = page.getByRole("button", { name: /Switch to (dark|light) theme/ });
    const current = await page.evaluate(() => document.documentElement.dataset.theme);
    if (current !== theme) await toggle.click();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe(theme);
    const nav = page.getByRole("navigation", { name: "Views" });
    for (const view of VIEWS) {
      await nav.getByRole("button", { name: view, exact: true }).click();
      await expect(page.locator("main")).toBeVisible();
      await page.waitForLoadState("networkidle");
      const result = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      expect(
        result.violations.map((v) => `${view}/${theme} ${v.id}: ${v.help} (${v.nodes.length})`),
      ).toEqual([]);
    }
    // Reduced motion: nothing animates or transitions anywhere.
    const moving = await page.evaluate(
      () =>
        [...document.querySelectorAll("*")].filter((el) => {
          const cs = getComputedStyle(el);
          return (
            (cs.animationName !== "none" && parseFloat(cs.animationDuration) > 0) ||
            parseFloat(cs.transitionDuration) > 0
          );
        }).length,
    );
    expect(moving).toBe(0);
    expect(foreign).toEqual([]);
  });
}

test("the daily path works from the keyboard alone, with a visible focus ring", async ({
  page,
}) => {
  await openStudio(page);
  // Skip link first, then into the form.
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  const prompt = page.getByLabel("Prompt", { exact: true });
  for (let i = 0; i < 40 && !(await prompt.evaluate((el) => el === document.activeElement)); i++)
    await page.keyboard.press("Tab");
  await expect(prompt).toBeFocused();
  await page.keyboard.type("a quiet lake at dawn, keyboard only");
  await page.keyboard.press("Control+Enter");
  const result = page.getByRole("region", { name: "Result" });
  await expect(result.getByText("a quiet lake at dawn, keyboard only")).toBeVisible({
    timeout: 20_000,
  });
  await expect(generateButton(page)).toBeVisible();
  // Tab forward to Download; every stop on the way shows a focus indicator.
  const download = result.getByRole("button", { name: "Download" });
  for (
    let i = 0;
    i < 60 && !(await download.evaluate((el) => el === document.activeElement));
    i++
  ) {
    await page.keyboard.press("Tab");
    const ring = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return true;
      const cs = getComputedStyle(el);
      return cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0;
    });
    expect(ring).toBe(true);
  }
  await expect(download).toBeFocused();
  const file = page.waitForEvent("download");
  await page.keyboard.press("Enter");
  await file;
});

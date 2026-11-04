import { expect, test, type Page } from "@playwright/test";
import { Actions, openStudio } from "./studio";

const nav = (page: Page, name: string) =>
  page.getByRole("navigation", { name: "Views" }).getByRole("button", { name });

async function apiGet<T>(page: Page, path: string): Promise<T> {
  return page.evaluate(async (p) => {
    const r = await fetch(p, {
      headers: { authorization: `Bearer ${sessionStorage.getItem("p11.token")}` },
    });
    return r.json();
  }, path) as Promise<T>;
}

test("a logo template draws exact text after the model's mark", async ({ page }) => {
  const foreign = await openStudio(page);
  const actions = new Actions(page);
  await actions.click(nav(page, "Templates")); // 1
  await expect(page.getByRole("listitem", { name: "Software logo dark" })).toBeVisible();
  await actions.click(page.getByRole("button", { name: "Run Software logo dark with inputs" })); // 2
  const dialog = page.getByRole("dialog", { name: /Run .Software logo dark/ });
  await dialog.getByLabel(/Text on the logo/).fill("ACME 42"); // typing: not counted
  await actions.click(dialog.getByRole("button", { name: "Run" })); // 3
  console.log(`[action-count] logo with text: ${actions.count}`);
  await expect
    .poll(
      async () =>
        (
          await apiGet<{ items: { template: string | null }[] }>(page, "/api/gallery?limit=10")
        ).items.filter((i) => i.template === "software-logo-dark").length,
      { timeout: 30_000 },
    )
    .toBeGreaterThan(0);

  const gallery = await apiGet<{
    items: { id: number; template: string | null; width: number | null }[];
  }>(page, "/api/gallery?limit=10");
  const made = gallery.items.find((i) => i.template === "software-logo-dark");
  expect(made).toBeTruthy();
  expect(made!.width).toBe(1024);
  const record = await apiGet<{
    recipe: { steps: { type: string; text?: string; font?: string }[] };
    bindings: Record<string, unknown>;
  }>(page, `/api/images/${made!.id}/recipe`);
  expect(record.recipe.steps.map((s) => s.type)).toEqual(["generate", "text_overlay"]);
  expect(record.recipe.steps[1]!.text).toBe("{{logo_text}}");
  expect(record.bindings.logo_text).toBe("ACME 42");
  expect(record.recipe.steps[1]!.font).toBe("display");
  expect(foreign).toEqual([]);
});

test("the Models page installs from a local server after the licence dialog", async ({ page }) => {
  const foreign = await openStudio(page);
  const actions = new Actions(page);
  await actions.click(nav(page, "Models")); // 1
  await expect(page.getByRole("heading", { name: "Models" })).toBeVisible();
  const row = page.getByRole("row", { name: /E2E test model/ });
  await expect(row.getByText("Not installed")).toBeVisible();
  await actions.click(row.getByRole("button", { name: "Install" })); // 2

  const dialog = page.getByRole("dialog", { name: "Install e2e-test-model" });
  await expect(dialog.getByText(/E2E test licence/)).toBeVisible();
  const install = dialog.getByRole("button", { name: "Install" });
  await expect(install).toBeDisabled();
  actions.count += 1; // 3: accept the licence
  await dialog.getByLabel(/I have read and accept/).check();
  await actions.click(install); // 4
  console.log(`[action-count] models install: ${actions.count}`);
  await expect(page.getByRole("region", { name: "Install progress" })).toBeVisible();
  await expect(row.getByText("Installed")).toBeVisible({ timeout: 20_000 });
  await expect(row.getByText(/E2E test licence · non-commercial/)).toBeVisible();

  await row.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByText(/file verified/)).toBeVisible();

  const models = await apiGet<{ id: string; state: string; verified: boolean }[]>(
    page,
    "/api/models",
  );
  const installed = models.find((m) => m.id === "e2e-test-model");
  expect(installed).toMatchObject({ state: "installed", verified: true });
  expect(foreign).toEqual([]);
});

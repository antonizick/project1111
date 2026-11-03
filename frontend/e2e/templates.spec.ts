import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { Actions, generateButton, openStudio } from "./studio";

// 64 x 64 teal PNG (synthetic; S6).
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAYElEQVR4nO3PQQ0AIBDAMED5SUcEj4ZkVbDtNbN+dnTAqwa0BrQGtAa0BrQGtAa0BrQGtAa0BrQGtAa0BrQGtAa0BrQGtAa0BrQGtAa0BrQGtAa0BrQGtAa0BrQGtAa0C4FEAYCt2yLnAAAAAElFTkSuQmCC",
  "base64",
);

/** GET an API path with the tab's session token. */
async function apiGet<T>(page: Page, path: string): Promise<T> {
  return page.evaluate(async (p) => {
    const r = await fetch(p, {
      headers: { authorization: `Bearer ${sessionStorage.getItem("p11.token")}` },
    });
    return r.json();
  }, path) as Promise<T>;
}

const nav = (page: Page, name: string) =>
  page.getByRole("navigation", { name: "Views" }).getByRole("button", { name });

test("save a result as a template in 2 actions, re-run it in 1, same recipe", async ({ page }) => {
  const foreign = await openStudio(page);
  await page.getByLabel("Prompt", { exact: true }).fill("a red kite over sand dunes");
  await generateButton(page).click();
  const result = page.getByRole("region", { name: "Result" });
  await expect(result.getByText("a red kite over sand dunes")).toBeVisible();

  const actions = new Actions(page);
  await actions.click(result.getByRole("button", { name: /Save as Template/ }));
  const dialog = page.getByRole("dialog", { name: "Save as Template" });
  await expect(dialog.getByLabel("Template name")).toHaveValue("a red kite over sand dunes");
  await dialog.getByLabel("Template name").fill("Kite e2e");
  await actions.click(dialog.getByRole("button", { name: "Save" }));
  await expect(page.getByText("Saved template “Kite e2e”.")).toBeVisible();
  expect(actions.count).toBeLessThanOrEqual(3);
  console.log(`[action-count] save as template: ${actions.count}`);

  await nav(page, "Templates").click();
  const card = page.getByRole("listitem", { name: "Kite e2e" });
  await expect(card).toBeVisible();
  const rerun = new Actions(page);
  await rerun.click(card.getByRole("button", { name: "Run Kite e2e" }));
  await expect(card.getByRole("img", { name: /Last result of Kite e2e/ })).toBeVisible();
  expect(rerun.count).toBe(1);
  console.log(`[action-count] re-run template: ${rerun.count}`);

  // the run used the template's settings: same generate step as the original image
  const gallery = await apiGet<{ items: { id: number; template: string | null }[] }>(
    page,
    "/api/gallery?limit=10",
  );
  const original = gallery.items.find((i) => i.template === null)!;
  const rerunImage = gallery.items.find((i) => i.template === "kite-e2e")!;
  const a = await apiGet<{ recipe: { steps: unknown[] } }>(
    page,
    `/api/images/${original.id}/recipe`,
  );
  const b = await apiGet<{ recipe: { steps: unknown[] } }>(
    page,
    `/api/images/${rerunImage.id}/recipe`,
  );
  expect(b.recipe.steps).toEqual(a.recipe.steps);
  expect(foreign).toEqual([]);
});

test("starter templates are installed and a one-slot run takes 3 actions", async ({ page }) => {
  const foreign = await openStudio(page);
  await nav(page, "Templates").click();
  for (const name of [
    "Wallpaper photoreal 16:9 1080p",
    "Wallpaper photoreal 16:9 1440p",
    "Software logo dark",
    "Software logo light",
    "Indie game logo",
    "3D animated avatar (bobblehead)",
  ])
    await expect(page.getByRole("listitem", { name })).toBeVisible();

  const card = page.getByRole("listitem", { name: "3D animated avatar (bobblehead)" });
  const actions = new Actions(page);
  await actions.click(card.getByRole("button", { name: /with inputs/ }));
  const dialog = page.getByRole("dialog", { name: /Run/ });
  actions.count += 1; // choosing the photo
  await dialog.getByLabel(/Face photo/).setInputFiles({
    name: "face.png",
    mimeType: "image/png",
    buffer: PNG,
  });
  await expect(dialog.getByText("Using face.png.")).toBeVisible();
  await actions.click(dialog.getByRole("button", { name: "Run" }));
  await expect(card.getByRole("img", { name: /Last result/ })).toBeVisible();
  expect(actions.count).toBe(3);
  console.log(`[action-count] run with one slot: ${actions.count}`);

  // a starter you delete stays deleted, with undo
  await page.getByRole("button", { name: "Delete Indie game logo" }).click();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.getByRole("listitem", { name: "Indie game logo" })).toBeVisible();
  expect(foreign).toEqual([]);
});

test("Ctrl+K runs a template from Generate; Templates view passes axe", async ({ page }) => {
  const foreign = await openStudio(page);
  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Run a template" });
  await palette.getByRole("combobox").fill("wallpaper 1080");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("region", { name: "Result" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Run Wallpaper photoreal 16:9 1080p" }),
  ).toBeVisible();

  await nav(page, "Templates").click();
  await expect(page.getByRole("listitem", { name: "Software logo dark" })).toBeVisible();
  const axe = await new AxeBuilder({ page }).analyze();
  expect(axe.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  expect(foreign).toEqual([]);
});

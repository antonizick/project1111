import { expect, test } from "@playwright/test";
import { launchUrl } from "./studio";

test("p11 open's one-time link starts a working session", async ({ page, browser }) => {
  const url = launchUrl();
  await page.goto(url);
  await expect(page.getByRole("heading", { name: "P11 Studio" })).toBeVisible();
  await expect(page.getByText(/Connected · v.* · fake engine/)).toBeVisible();
  expect(new URL(page.url()).hash).toBe("");
  // The cookie lets the page load API images; the token stays out of the URL.
  const gallery = await page.evaluate(async () => {
    const token = sessionStorage.getItem("p11.token") ?? "";
    const r = await fetch("/api/gallery", { headers: { authorization: `Bearer ${token}` } });
    return r.status;
  });
  expect(gallery).toBe(200);
  // The same link does not work twice (a fresh browser context has no session).
  const other = await (await browser.newContext()).newPage();
  await other.goto(url);
  await expect(other.getByRole("alert")).toContainText("already used");
});

test("the page loads under the strict CSP without violations", async ({ page }) => {
  const violations: string[] = [];
  page.on("console", (m) => {
    if (/Content Security Policy/i.test(m.text())) violations.push(m.text());
  });
  await page.goto(launchUrl());
  await expect(page.getByText(/Connected · v/)).toBeVisible();
  await page.getByRole("button", { name: "Gallery" }).click();
  await expect(page.getByRole("group", { name: "Images" })).toBeVisible();
  expect(violations).toEqual([]);
});

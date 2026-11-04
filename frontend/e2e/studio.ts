// Shared helpers for the Studio walkthroughs: a launch URL from `p11 open`, a guard that fails
// the test on any request that leaves 127.0.0.1:<port> (S1), and an Appendix B action counter.

import { execFileSync } from "node:child_process";
import { expect, type Page } from "@playwright/test";
import { studioEnv } from "../playwright.config";

export function launchUrl(): string {
  return execFileSync("uv", ["run", "p11", "open", "--print-url"], {
    cwd: "..",
    env: studioEnv,
    encoding: "utf8",
  }).trim();
}

/** Every request must go to the Studio's own origin (or be a data:/blob: URL). */
export function guardNetwork(page: Page): string[] {
  const foreign: string[] = [];
  const origin = `http://127.0.0.1:${studioEnv.P11_STUDIO_PORT}`;
  page.on("request", (r) => {
    const url = r.url();
    if (!(url.startsWith(`${origin}/`) || url.startsWith("data:") || url.startsWith("blob:")))
      foreign.push(url);
  });
  return foreign;
}

export async function openStudio(page: Page): Promise<string[]> {
  const foreign = guardNetwork(page);
  await page.goto(launchUrl());
  await expect(page.getByText(/Connected · v/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Photoreal" })).toBeVisible();
  return foreign;
}

/** Counts actions as Appendix B defines them: a click or a key chord (typing is free). */
export class Actions {
  count = 0;
  constructor(private readonly page: Page) {}
  async click(target: ReturnType<Page["getByRole"]>) {
    this.count += 1;
    await target.click();
  }
  async press(chord: string) {
    this.count += 1;
    await this.page.keyboard.press(chord);
  }
}

export const generateButton = (page: Page) =>
  page.getByRole("form", { name: "Generate" }).getByRole("button", { name: "Generate" });

/** A synthetic photo made in the page (no files in the repo; S6). */
export async function syntheticPng(page: Page, w: number, h: number): Promise<Buffer> {
  const b64 = await page.evaluate(
    ([w, h]) => {
      const c = document.createElement("canvas");
      c.width = w;
      c.height = h;
      const g = c.getContext("2d")!;
      const grad = g.createLinearGradient(0, 0, w, h);
      grad.addColorStop(0, "#245");
      grad.addColorStop(1, "#c96");
      g.fillStyle = grad;
      g.fillRect(0, 0, w, h);
      return new Promise<string>((resolve) =>
        c.toBlob(async (blob) => {
          const bytes = new Uint8Array(await blob!.arrayBuffer());
          let s = "";
          for (const x of bytes) s += String.fromCharCode(x);
          resolve(btoa(s));
        }, "image/png"),
      );
    },
    [w, h] as const,
  );
  return Buffer.from(b64, "base64");
}

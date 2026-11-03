import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "../../App";
import type { Recipe } from "../../api/types";
import {
  baseRoutes,
  createSource,
  FakeSource,
  image,
  job,
  mockApi,
  Problem,
} from "../../test/fakes";

beforeEach(() => {
  sessionStorage.setItem("p11.token", "tok-abcdefghijkl");
  vi.stubGlobal(
    "URL",
    Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => undefined }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function start(routes = {}) {
  const api = mockApi({ ...baseRoutes(), ...routes });
  render(<App createSource={createSource} />);
  await screen.findByRole("button", { name: "Photoreal" });
  act(() => FakeSource.last!.onopen?.(new Event("open")));
  return api;
}

const genButton = () =>
  within(screen.getByRole("form", { name: "Generate" })).getByRole("button", { name: "Generate" });

const emit = (type: string, data: unknown) => act(() => FakeSource.last!.emit(type, data));

it("generates from a typed prompt with Ctrl+Enter, shows progress and the result", async () => {
  const user = userEvent.setup();
  const { calls } = await start({ "POST /api/jobs": () => job() });
  await user.type(screen.getByLabelText("Prompt"), "a lighthouse at dusk");
  await user.keyboard("{Control>}{Enter}{/Control}");
  const submit = calls.find((c) => c.method === "POST" && c.path === "/api/jobs");
  const recipe = (submit?.body as { recipe: Recipe; count: number }).recipe;
  expect(recipe.steps[0]).toMatchObject({
    prompt: "a lighthouse at dusk",
    style: "photoreal",
    aspect: null,
  });
  expect(screen.getByText("Waiting in the queue")).toBeVisible();
  emit("job", job({ state: "running", updated_at: new Date().toISOString() }));
  emit("progress", {
    job: "job1",
    run: 0,
    runs: 1,
    graph: 0,
    graphs: 1,
    progress: 0.4,
    step: 2,
    total: 5,
    title: "base",
  });
  expect(screen.getByText("Generating · step 2/5")).toBeVisible();
  expect(screen.getByText(/40 % · about \d+ s left/)).toBeVisible();
  emit("job", job({ state: "running", note: "Out of GPU memory: retrying in low-memory mode." }));
  expect(screen.getByText(/retrying in low-memory mode/)).toBeVisible();
  emit("image", { job: "job1", image: image(5) });
  emit("job", job({ state: "done", images: [5], progress: 1 }));
  const result = await screen.findByRole("region", { name: "Result" });
  expect(within(result).getByText("prompt 5")).toBeVisible();
  expect(within(result).getByRole("button", { name: "Inpaint" })).toBeEnabled();
  expect(within(result).getByRole("button", { name: "Background" })).toBeEnabled();
  expect(screen.getByText("Model: realvisxl5-lightning")).toBeVisible();
});

it("switches presets and shows the model's manifest defaults in Advanced", async () => {
  const user = userEvent.setup();
  const { calls } = await start({ "POST /api/jobs": () => job() });
  expect(screen.getByRole("button", { name: "Wallpaper 1920 x 1080 (16:9)" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await user.click(screen.getByRole("button", { name: "Logo (flat)" }));
  expect(screen.getByRole("button", { name: "Logo (square)" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await user.click(screen.getByRole("button", { name: "Square 1024" }));
  await user.click(screen.getByRole("button", { name: "▸ Advanced" }));
  expect(screen.getByLabelText("Steps")).toHaveAttribute("placeholder", "5");
  expect(screen.getByText(/Model defaults: dpmpp_sde \/ karras, 5 steps, CFG 1.5/)).toBeVisible();
  await user.selectOptions(screen.getByLabelText("Model"), "juggernautxl9");
  expect(screen.getByLabelText("Steps")).toHaveAttribute("placeholder", "30");
  await user.type(screen.getByLabelText("Steps"), "12");
  await user.click(screen.getByLabelText("Lock seed"));
  fireEvent.change(screen.getByLabelText("Seed"), { target: { value: "99" } });
  await user.type(screen.getByLabelText("Prompt"), "fox logo");
  await user.click(genButton());
  const body = calls.find((c) => c.path === "/api/jobs")?.body as { recipe: Recipe };
  expect(body.recipe.steps[0]).toMatchObject({
    style: "logo-flat",
    aspect: "1:1-1024",
    model: { manifest_id: "juggernautxl9" },
    sampler: { steps: 12, cfg: null },
  });
  expect(body.recipe.seed).toEqual({ kind: "increment", start: 99 });
});

it("shows a plain-English toast with a Models link when a model is missing", async () => {
  const user = userEvent.setup();
  await start({
    "POST /api/jobs": () =>
      new Problem(409, {
        code: "models.missing",
        message: "Model 'x' is missing.",
        hint: "Run `p11 models install default`.",
      }),
  });
  await user.type(screen.getByLabelText("Prompt"), "x");
  await user.click(genButton());
  const alert = await screen.findByText("Model 'x' is missing.");
  expect(screen.getByText("Run `p11 models install default`.")).toBeVisible();
  await user.click(
    within(alert.closest(".toast") as HTMLElement).getByRole("button", { name: "Models" }),
  );
  expect(screen.getByRole("button", { name: /^Models/ })).toHaveAttribute("aria-current", "page");
  expect(await screen.findByRole("heading", { name: "Models" })).toBeVisible();
});

it("cancels with Esc, asks for a prompt first, and reports failed jobs", async () => {
  const user = userEvent.setup();
  const { calls } = await start({
    "POST /api/jobs": () => job(),
    "POST /api/jobs/job1/cancel": () => job({ state: "cancelled" }),
  });
  await user.click(genButton());
  expect(screen.getByText("Type what you want to see first.")).toBeInTheDocument();
  await user.type(screen.getByLabelText("Prompt"), "x");
  await user.click(genButton());
  await user.keyboard("{Escape}");
  expect(calls.some((c) => c.path === "/api/jobs/job1/cancel")).toBe(true);
  emit(
    "job",
    job({
      state: "failed",
      error: { code: "engine.oom", message: "Out of GPU memory.", hint: "Try a smaller preset." },
    }),
  );
  expect(await screen.findByText("Out of GPU memory.")).toBeVisible();
  expect(screen.getByText("Try a smaller preset.")).toBeVisible();
});

it("runs follow-up actions on the result and opens the shortcut overlay", async () => {
  const user = userEvent.setup();
  let n = 0;
  const { calls } = await start({
    "GET /api/templates": () => [],
    "POST /api/jobs": () => job({ id: `job${++n}` }),
    "POST /api/images/5/variations": () => ({ jobs: [job({ id: "job2" })] }),
    "POST /api/images/5/favourite": () => image(5, { favourite: true }),
    "POST /api/images/5/export": () => new Blob(["png"]),
  });
  await user.type(screen.getByLabelText("Prompt"), "x");
  await user.click(genButton());
  emit("image", { job: "job1", image: image(5) });
  emit("job", job({ state: "done", images: [5] }));
  await screen.findByRole("region", { name: "Result" });
  await user.click(screen.getByRole("button", { name: "☆ Favourite" }));
  expect(await screen.findByRole("button", { name: "★ Favourite" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Download" }));
  expect(calls.find((c) => c.path === "/api/images/5/export")?.body).toEqual({
    strip_metadata: true,
  });
  await user.click(screen.getByRole("button", { name: /Save as Template/ }));
  expect(screen.getByRole("dialog", { name: "Save as Template" })).toBeInTheDocument();
  await user.keyboard("{Escape}");
  await user.click(screen.getByRole("button", { name: /Upscale…/ }));
  const upscaleDialog = screen.getByRole("dialog", { name: "Upscale" });
  await user.click(within(upscaleDialog).getByRole("button", { name: "Upscale ×2" }));
  const up = calls.filter((c) => c.path === "/api/jobs").at(-1)?.body as {
    recipe: Recipe;
    parent: number;
  };
  expect(up.parent).toBe(5);
  expect(up.recipe.source_image).toEqual({ ref: "gallery/5" });
  (document.activeElement as HTMLElement).blur();
  await user.keyboard("v");
  expect(calls.find((c) => c.path === "/api/images/5/variations")?.body).toEqual({
    mode: "seed",
    count: 1,
  });
  expect(screen.getByText("Waiting in the queue")).toBeVisible();
  await user.keyboard("?");
  const dialog = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
  expect(within(dialog).getByText("Ctrl+Enter")).toBeVisible();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  await user.keyboard("g");
  expect(screen.getByRole("button", { name: "Gallery" })).toHaveAttribute("aria-current", "page");
});

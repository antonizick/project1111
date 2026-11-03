import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "../../App";
import type { Recipe } from "../../api/types";
import { baseRoutes, createSource, FakeSource, image, job, mockApi } from "../../test/fakes";

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

const genButton = () =>
  within(screen.getByRole("form", { name: "Generate" })).getByRole("button", { name: "Generate" });

async function start(routes = {}) {
  const api = mockApi({ ...baseRoutes(), ...routes });
  render(<App createSource={createSource} />);
  await screen.findByRole("button", { name: "Photoreal" });
  act(() => FakeSource.last!.onopen?.(new Event("open")));
  return api;
}

it("applies exact text as a text_overlay job on the image", async () => {
  const user = userEvent.setup();
  const { calls } = await start({
    "POST /api/jobs": () => job(),
    "GET /api/text/fonts": () => ({
      fonts: [
        { id: "sans", label: "Inter", weights: ["regular", "bold"], licence: "OFL", source: "" },
      ],
    }),
    "POST /api/text/preview": () => new Blob(["png"], { type: "image/png" }),
  });
  await user.type(screen.getByLabelText("Prompt"), "a paper plane");
  await user.click(genButton());
  act(() => {
    FakeSource.last!.emit("image", { job: "job1", image: image(5) });
    FakeSource.last!.emit("job", job({ state: "done", images: [5] }));
  });
  await screen.findByRole("region", { name: "Result" });
  await user.click(screen.getByRole("button", { name: "Add text / Logo" }));
  await screen.findByRole("dialog", { name: "Text & logo" });
  await user.click(screen.getByRole("button", { name: "Apply text" }));
  const sent = calls.filter((c) => c.path === "/api/jobs").at(-1)?.body as {
    recipe: Recipe;
    parent: number;
  };
  expect(sent.parent).toBe(5);
  expect(sent.recipe.source_image).toEqual({ ref: "gallery/5" });
  expect(sent.recipe.steps).toHaveLength(1);
  expect(sent.recipe.steps[0]).toMatchObject({
    type: "text_overlay",
    text: "Product Name",
    font: "sans",
    shadow: true,
    also_prompt_model: false,
  });
  expect(screen.queryByRole("dialog", { name: "Text & logo" })).toBeNull();
});

it("offers logo variations and a transparent logo pack", async () => {
  const user = userEvent.setup();
  const { calls } = await start({
    "POST /api/jobs": () => job(),
    "POST /api/images/5/variations": () => ({ jobs: [job({ id: "job2" })] }),
    "POST /api/images/5/logo-export": () => new Blob(["zip"]),
  });
  await user.type(screen.getByLabelText("Prompt"), "x");
  await user.click(genButton());
  act(() => {
    FakeSource.last!.emit("image", { job: "job1", image: image(5) });
    FakeSource.last!.emit("job", job({ state: "done", images: [5] }));
  });
  await screen.findByRole("region", { name: "Result" });
  await user.click(screen.getByRole("button", { name: "Add text / Logo" }));
  await screen.findByRole("dialog", { name: "Text & logo" });
  await user.click(screen.getByRole("button", { name: "6 logo variations" }));
  expect(calls.find((c) => c.path === "/api/images/5/variations")?.body).toEqual({
    mode: "seed",
    count: 6,
  });
  await user.click(screen.getByRole("button", { name: "Add text / Logo" }));
  await screen.findByRole("dialog", { name: "Text & logo" });
  await user.click(screen.getByRole("button", { name: /Logo pack/ }));
  expect(calls.find((c) => c.path === "/api/images/5/logo-export")?.body).toEqual({
    transparent: true,
    sizes: [512, 256, 128, 64, 32],
  });
});

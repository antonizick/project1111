// The gallery picker (Phase 17g, ADR-0046): search, paging, the empty state, keyboard use, and that
// every image control hands over a `gallery/<id>` reference and uploads nothing.

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "../App";
import type { Slot } from "../api/types";
import { baseRoutes, createSource, image, job, mockApi, template, type Route } from "../test/fakes";

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

const all = [7, 6, 5].map((i) => image(i, { prompt: i === 7 ? "a red fox" : `prompt ${i}` }));

const galleryRoute: Route = (_i, url) => {
  const q = url.searchParams.get("q") ?? "";
  const list = all.filter((i) => i.prompt.includes(q));
  return { items: list, total: list.length, limit: 60, offset: 0 };
};

async function start(routes: Record<string, Route> = {}) {
  const user = userEvent.setup();
  const api = mockApi({
    ...baseRoutes(),
    "GET /api/gallery": galleryRoute,
    "POST /api/jobs": () => job(),
    ...routes,
  });
  render(<App createSource={createSource} />);
  await screen.findByRole("form", { name: "Generate" });
  return { user, ...api };
}

const view = (name: RegExp) =>
  within(screen.getByRole("navigation", { name: "Views" })).getByText(name);

/** Open the picker named `label` and choose the image with `alt`. */
async function pick(user: ReturnType<typeof userEvent.setup>, label: string, alt = "a red fox") {
  await user.click(screen.getByRole("button", { name: `From gallery for ${label}` }));
  const dialog = await screen.findByRole("dialog", { name: new RegExp(label) });
  await user.click(await within(dialog).findByRole("button", { name: alt }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: /gallery/ })).toBeNull());
}

const uploads = (calls: { method: string; path: string }[]) =>
  calls.filter((c) => c.path === "/api/uploads").length;

it("searches, and says so when nothing matches", async () => {
  const { user } = await start();
  await user.click(screen.getByRole("button", { name: "From gallery for Start from a photo" }));
  const dialog = await screen.findByRole("dialog", { name: /Start from a photo/ });
  expect(await within(dialog).findAllByRole("img")).toHaveLength(3);
  expect(within(dialog).getByRole("searchbox")).toHaveFocus();
  await user.type(within(dialog).getByRole("searchbox"), "fox");
  await waitFor(() => expect(within(dialog).getAllByRole("img")).toHaveLength(1));
  await user.type(within(dialog).getByRole("searchbox"), "zzz");
  expect(await within(dialog).findByText(/Nothing matches/)).toBeVisible();
});

it("offers an empty gallery message", async () => {
  const { user } = await start({
    "GET /api/gallery": () => ({ items: [], total: 0, limit: 60, offset: 0 }),
  });
  await user.click(screen.getByRole("button", { name: "From gallery for Start from a photo" }));
  expect(await screen.findByText(/No images yet/)).toBeVisible();
});

it("pages through the gallery", async () => {
  const { user, calls } = await start({
    "GET /api/gallery": (_i, url) => {
      const offset = Number(url.searchParams.get("offset"));
      const items = offset === 0 ? all.slice(0, 2) : all.slice(2);
      return { items, total: 3, limit: 60, offset };
    },
  });
  await user.click(screen.getByRole("button", { name: "From gallery for Start from a photo" }));
  const dialog = await screen.findByRole("dialog", { name: /Start from a photo/ });
  await user.click(await within(dialog).findByRole("button", { name: /Show more \(1 left\)/ }));
  await waitFor(() => expect(within(dialog).getAllByRole("img")).toHaveLength(3));
  expect(within(dialog).queryByRole("button", { name: /Show more/ })).toBeNull();
  expect(calls.some((c) => c.url.searchParams.get("offset") === "2")).toBe(true);
});

it("works from the keyboard, and Enter in the search box submits nothing", async () => {
  const { user, calls } = await start();
  await user.click(screen.getByRole("button", { name: "From gallery for Start from a photo" }));
  const dialog = await screen.findByRole("dialog", { name: /Start from a photo/ });
  await within(dialog).findAllByRole("img");
  await user.keyboard("{Enter}");
  expect(calls.some((c) => c.path === "/api/jobs")).toBe(false);
  await user.tab();
  await user.keyboard("{Enter}");
  await waitFor(() => expect(screen.getByAltText("Starting photo")).toBeVisible());
  await user.click(screen.getByRole("button", { name: "Remove photo" }));
  await user.click(screen.getByRole("button", { name: "From gallery for Start from a photo" }));
  await screen.findByRole("dialog", { name: /Start from a photo/ });
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("Generate: Start from a photo passes the reference and the parent", async () => {
  const { user, calls } = await start();
  await pick(user, "Start from a photo");
  await user.type(screen.getByLabelText("Prompt"), "a fox in snow");
  await user.keyboard("{Control>}{Enter}{/Control}");
  await waitFor(() => expect(calls.some((c) => c.path === "/api/jobs")).toBe(true));
  const body = calls.find((c) => c.path === "/api/jobs")?.body as {
    recipe: { source_image: unknown };
    parent: number;
  };
  expect(body.recipe.source_image).toEqual({ ref: "gallery/7" });
  expect(body.parent).toBe(7);
  expect(uploads(calls)).toBe(0);
});

it("Inpaint: the picked image opens in the editor and uploads nothing", async () => {
  const { user, calls } = await start();
  await user.click(view(/^Inpaint$/));
  await pick(user, "Upload photo");
  await screen.findByRole("button", { name: /Apply/ });
  expect(screen.queryByRole("heading", { name: /Fix or change part/ })).toBeNull();
  expect(uploads(calls)).toBe(0);
  expect(screen.getByLabelText("Only masked area at full resolution")).not.toBeChecked();
});

it("Background: subject and background photo are references", async () => {
  const { user, calls } = await start({
    "POST /api/background/mask": () => new Blob(["mask"]),
    "POST /api/uploads": () => ({ id: "img-mask", kind: "mask", width: 8, height: 8 }),
    "POST /api/background/preview": () => new Blob(["png"]),
  });
  await user.click(view(/^Background$/));
  await pick(user, "Upload photo");
  await waitFor(() =>
    expect(calls.find((c) => c.path === "/api/background/mask")?.body).toMatchObject({
      image: { ref: "gallery/7" },
    }),
  );
  await pick(user, "Background photo", "prompt 6");
  expect(await screen.findByAltText("Background")).toBeVisible();
  await waitFor(
    () =>
      expect(calls.filter((c) => c.path === "/api/background/preview").at(-1)?.body).toMatchObject({
        image: { ref: "gallery/7" },
        background: { ref: "gallery/6" },
      }),
    { timeout: 2000 },
  );
  // The only upload is the auto-mask.
  const sent = calls.filter((c) => c.path === "/api/uploads");
  expect(sent).toHaveLength(1);
  expect(sent[0]?.url.searchParams.get("kind")).toBe("mask");
});

it("Face: picture, face photo, pose photo and reference are references", async () => {
  const { user, calls } = await start({
    "POST /api/face/detect": () => ({ faces: [], width: 8, height: 8 }),
  });
  await user.click(view(/^Face/));
  await pick(user, "Picture");
  await pick(user, "Face photo", "prompt 6");
  await user.click(screen.getAllByRole("button", { name: "Swap face" }).at(-1) as HTMLElement);
  await waitFor(() => expect(calls.some((c) => c.path === "/api/jobs")).toBe(true));
  const jobs = () =>
    calls.filter((c) => c.path === "/api/jobs").map((c) => c.body) as {
      recipe: { source_image: unknown };
      bindings: unknown;
      parent: number | null;
    }[];
  expect(jobs()[0]?.recipe.source_image).toEqual({ ref: "gallery/7" });
  expect(jobs()[0]?.bindings).toEqual({ face: { ref: "gallery/6" } });
  expect(jobs()[0]?.parent).toBe(7);

  await user.click(screen.getByRole("button", { name: "Use as reference" }));
  await pick(user, "Reference image", "prompt 5");
  const face = screen.getByRole("region", { name: /Face/ });
  await user.type(within(face).getByLabelText("Prompt"), "a castle");
  await user.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(jobs()).toHaveLength(2));
  expect(jobs()[1]?.bindings).toEqual({ reference: { ref: "gallery/5" } });

  await user.click(screen.getByRole("button", { name: "Apply pose" }));
  await user.selectOptions(screen.getByLabelText("Pose from"), "photo");
  await pick(user, "Pose photo", "prompt 6");
  await user.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(jobs()).toHaveLength(3));
  expect(jobs()[2]?.bindings).toEqual({ pose: { ref: "gallery/6" } });
  expect(uploads(calls)).toBe(0);
});

it("Video: the face photo is a reference", async () => {
  const { user, calls } = await start({
    "GET /api/video/jobs": () => [],
  });
  await user.click(view(/^Video$/));
  await pick(user, "Face photo");
  expect(await screen.findByAltText("Image 7")).toBeVisible();
  expect(uploads(calls)).toBe(0);
});

it("Templates: image slots offer the picker, mask slots do not", async () => {
  const slots: Slot[] = [
    { name: "face", kind: "face_image", label: "Face photo", required: true, default: null },
    { name: "mask", kind: "mask", label: "Mask", required: false, default: null },
  ];
  const { user, calls } = await start({
    "GET /api/templates": () => [template({ id: "t2", name: "Avatar", slots })],
  });
  await user.click(view(/^Templates$/));
  await user.click(await screen.findByRole("button", { name: "Run Avatar" }));
  expect(screen.queryByRole("button", { name: "From gallery for Mask" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "From gallery for Face photo" }));
  const picker = await screen.findByRole("dialog", { name: /choose from the gallery/ });
  await user.click(await within(picker).findByRole("button", { name: "a red fox" }));
  const run = screen.getByRole("dialog", { name: /Run/ });
  await within(run).findByText("Using Image 7.");
  await user.click(within(run).getByRole("button", { name: "Run" }));
  await waitFor(() => expect(calls.some((c) => c.path === "/api/jobs")).toBe(true));
  const body = calls.find((c) => c.path === "/api/jobs")?.body as { bindings: unknown };
  expect(body.bindings).toEqual({ face: { ref: "gallery/7" } });
  expect(uploads(calls)).toBe(0);
});

import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "../../App";
import { baseRoutes, createSource, FakeSource, image, mockApi } from "../../test/fakes";

const items = [
  image(3, { favourite: true }),
  image(2),
  image(1, { created_at: "2026-10-01T10:00:00Z" }),
];

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

async function openGallery(routes = {}) {
  const user = userEvent.setup();
  const api = mockApi({
    ...baseRoutes(),
    "GET /api/gallery": (_i, url) => {
      const q = url.searchParams.get("q");
      const list = q ? items.filter((i) => i.prompt.includes(q)) : items;
      return { items: list, total: list.length, limit: 120, offset: 0 };
    },
    "GET /api/gallery/facets": () => ({ templates: ["scenes"], models: ["realvisxl5-lightning"] }),
    "GET /api/trash": () => ({ count: 2, bytes: 4096 }),
    ...routes,
  });
  render(<App createSource={createSource} />);
  await user.click(await screen.findByRole("button", { name: "Gallery" }));
  await screen.findByRole("button", { name: "Open: prompt 3" });
  return { user, ...api };
}

it("lists images by day, searches and filters", async () => {
  const { user, calls } = await openGallery();
  const list = screen.getByRole("list", { name: "Images" });
  expect(within(list).getAllByRole("listitem")).toHaveLength(3);
  expect(within(list).getAllByRole("heading", { level: 3 })).toHaveLength(2);
  expect(screen.getByText("3 images")).toBeVisible();
  expect(screen.getByText("Trash: 2 images (4 KB)")).toBeVisible();
  await user.type(screen.getByLabelText("Search prompts"), "prompt 2");
  await waitFor(() => expect(screen.getByText("1 image")).toBeVisible());
  await user.selectOptions(screen.getByLabelText("Filter by model"), "realvisxl5-lightning");
  await user.click(screen.getByRole("button", { name: "★ Favourites" }));
  await waitFor(() => {
    const last = calls.filter((c) => c.path === "/api/gallery").at(-1)!.url.searchParams;
    expect([last.get("q"), last.get("model"), last.get("favourites")]).toEqual([
      "prompt 2",
      "realvisxl5-lightning",
      "true",
    ]);
  });
});

it("compares, exports and deletes a selection, and empties the trash after confirming", async () => {
  const { user, calls } = await openGallery({
    "POST /api/gallery/export": () => new Blob(["zip"]),
    "DELETE /api/images/3": () => ({ deleted: 3, trash: { count: 3, bytes: 6000 } }),
    "DELETE /api/images/2": () => ({ deleted: 2, trash: { count: 4, bytes: 8000 } }),
    "POST /api/trash/empty": () => ({ count: 0, bytes: 0 }),
  });
  await user.click(screen.getByLabelText("Select image 3"));
  expect(screen.getByRole("button", { name: "Compare" })).toBeDisabled();
  await user.click(screen.getByLabelText("Select image 2"));
  await user.click(screen.getByRole("button", { name: "Compare" }));
  const compare = screen.getByRole("dialog", { name: "Compare 2 images" });
  await user.click(within(compare).getByRole("button", { name: "Zoom in" }));
  expect(within(compare).getAllByRole("img", { name: /zoom 125 %/ })).toHaveLength(2); // synced
  await user.keyboard("{Escape}");
  await user.click(screen.getByLabelText("Strip metadata"));
  await user.click(screen.getByRole("button", { name: "Export 2" }));
  expect(calls.find((c) => c.path === "/api/gallery/export")?.body).toEqual({
    ids: [3, 2],
    strip_metadata: false,
  });
  await user.click(screen.getByRole("button", { name: "Delete 2" }));
  expect(await screen.findByText("Moved 2 images to the P11 trash.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Empty trash" }));
  const confirm = screen.getByRole("dialog", { name: "Empty the trash?" });
  await user.click(within(confirm).getByRole("button", { name: "Delete for good" }));
  expect(await screen.findByText("The trash is empty.")).toBeInTheDocument();
  expect(calls.some((c) => c.path === "/api/trash/empty")).toBe(true);
});

it("opens a detail view and re-opens an image as a recipe", async () => {
  const { user } = await openGallery({
    "GET /api/images/3/recipe": () => ({
      recipe: {
        schema_version: 1,
        id: "r",
        name: "n",
        tags: [],
        folder: "",
        slots: [],
        seed: { kind: "random" },
        created_at: "2026-11-03T10:00:00Z",
        source_image: null,
        steps: [
          {
            type: "generate",
            prompt: "prompt 3",
            negative: "",
            style: "logo-3d",
            aspect: "logo-1:1",
            model: null,
            loras: [],
            sampler: null,
            chain: null,
            quality: false,
            batch_size: 1,
          },
        ],
      },
      bindings: {},
      seed: 103,
      template: null,
      timings: {},
      model_hashes: {},
    }),
  });
  await user.click(screen.getByRole("button", { name: "Open: prompt 3" }));
  const dialog = screen.getByRole("dialog", { name: "prompt 3" });
  expect(within(dialog).getByRole("button", { name: "★ Favourite" })).toBeVisible();
  await user.click(within(dialog).getByRole("button", { name: "Next →" }));
  expect(screen.getByRole("dialog", { name: "prompt 2" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "← Previous" }));
  await user.click(screen.getByRole("button", { name: "Open as recipe" }));
  await waitFor(() => expect(screen.getByLabelText("Prompt")).toHaveValue("prompt 3"));
  expect(screen.getByRole("button", { name: "Logo (3D)" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByLabelText("Seed")).toHaveValue(103);
  expect(screen.getByLabelText("Lock seed")).toBeChecked();
});

it("explains the empty gallery and live-updates on new images", async () => {
  const user = userEvent.setup();
  let list: ReturnType<typeof image>[] = [];
  mockApi({
    ...baseRoutes(),
    "GET /api/gallery": () => ({ items: list, total: list.length, limit: 120, offset: 0 }),
  });
  render(<App createSource={createSource} />);
  await user.click(await screen.findByRole("button", { name: "Gallery" }));
  expect(await screen.findByText("No images yet")).toBeVisible();
  list = [image(8)];
  act(() => FakeSource.last!.emit("image", { job: "j", image: image(8) }));
  expect(await screen.findByRole("button", { name: "Open: prompt 8" })).toBeVisible();
});

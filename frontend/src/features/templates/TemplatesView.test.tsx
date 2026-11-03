import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "../../App";
import {
  baseRoutes,
  createSource,
  FakeSource,
  image,
  job,
  mockApi,
  template,
} from "../../test/fakes";

beforeEach(() => {
  sessionStorage.setItem("p11.token", "tok-abcdefghijkl");
  localStorage.clear();
  vi.stubGlobal(
    "URL",
    Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => undefined }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const scene = {
  name: "scene",
  kind: "text" as const,
  label: "Scene",
  required: false,
  default: "a lake",
};
const needsFace = template({
  id: "face1",
  name: "Avatar",
  slug: "avatar",
  folder: "",
  tags: ["avatar"],
  slots: [{ name: "face", kind: "face_image", label: "Face photo", required: true, default: null }],
});
const wallpaper = template({ slots: [scene] });
const logo = template({ id: "logo1", name: "Logo dark", slug: "logo-dark", tags: ["mark-only"] });

async function start(routes = {}) {
  const api = mockApi({ ...baseRoutes(), ...routes });
  render(<App createSource={createSource} />);
  await screen.findByRole("button", { name: "Photoreal" });
  act(() => FakeSource.last!.onopen?.(new Event("open")));
  return api;
}

it("lists templates with folders and tags, and Run is one click", async () => {
  const user = userEvent.setup();
  const { calls } = await start({
    "GET /api/templates": () => [wallpaper, logo],
    "POST /api/jobs": () => job(),
  });
  await user.click(
    within(screen.getByRole("navigation", { name: "Views" })).getByText("Templates"),
  );
  expect(await screen.findByRole("listitem", { name: wallpaper.name })).toBeVisible();
  expect(screen.getByText(/arrives with the text overlay/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: `Run ${wallpaper.name}` }));
  const submit = calls.find((c) => c.method === "POST" && c.path === "/api/jobs");
  expect(submit?.body).toMatchObject({ template: wallpaper.slug, bindings: {} });
  expect((submit?.body as { recipe: unknown }).recipe).toEqual(wallpaper.recipe);
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("asks for a missing required slot, uploads the photo and remembers it", async () => {
  const user = userEvent.setup();
  const { calls } = await start({
    "GET /api/templates": () => [needsFace],
    "POST /api/uploads": () => ({ id: "img-1", kind: "image", width: 8, height: 8 }),
    "POST /api/jobs": () => job(),
  });
  await user.click(
    within(screen.getByRole("navigation", { name: "Views" })).getByText("Templates"),
  );
  await user.click(await screen.findByRole("button", { name: "Run Avatar" }));
  const dialog = screen.getByRole("dialog", { name: /Run/ });
  const run = within(dialog).getByRole("button", { name: "Run" });
  expect(run).toBeDisabled();
  await user.upload(
    within(dialog).getByLabelText(/Face photo/),
    new File(["x"], "me.png", { type: "image/png" }),
  );
  await within(dialog).findByText("Using me.png.");
  await user.click(within(dialog).getByLabelText(/Remember/));
  await user.click(run);
  const body = calls.find((c) => c.path === "/api/jobs")?.body as { bindings: unknown };
  expect(body.bindings).toEqual({ face: { ref: "img-1" } });
  // next time the remembered photo runs it in one click
  await user.click(screen.getByRole("button", { name: "Run Avatar" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(calls.filter((c) => c.path === "/api/jobs")).toHaveLength(2);
});

it("deletes with an undo toast and imports a file", async () => {
  const user = userEvent.setup();
  const store = [wallpaper];
  const { calls } = await start({
    "GET /api/templates": () => [...store],
    "DELETE /api/templates/tpl1": () => {
      store.length = 0;
      return null;
    },
    "POST /api/templates": () => {
      store.push(wallpaper);
      return wallpaper;
    },
    "POST /api/templates/import": () => template({ id: "imp", name: "Imported" }),
  });
  await user.click(
    within(screen.getByRole("navigation", { name: "Views" })).getByText("Templates"),
  );
  await user.click(await screen.findByRole("button", { name: `Delete ${wallpaper.name}` }));
  expect(await screen.findByText(`Deleted “${wallpaper.name}”.`)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Undo" }));
  expect(await screen.findByRole("listitem", { name: wallpaper.name })).toBeVisible();
  expect(calls.some((c) => c.method === "POST" && c.path === "/api/templates")).toBe(true);
  await user.upload(
    screen.getByLabelText("Import a template file"),
    new File(['{"schema_version":1}'], "x.p11template.json", { type: "application/json" }),
  );
  expect(await screen.findByText("Imported “Imported”.")).toBeVisible();
});

it("Save as Template takes two actions from a result and posts the choices", async () => {
  const user = userEvent.setup();
  const { calls } = await start({
    "POST /api/jobs": () => job(),
    "POST /api/templates/from-image": () => wallpaper,
  });
  await user.type(screen.getByLabelText("Prompt", { exact: true }), "a lighthouse at dusk");
  await user.click(
    within(screen.getByRole("form", { name: "Generate" })).getByRole("button", {
      name: "Generate",
    }),
  );
  act(() =>
    FakeSource.last!.emit("image", { job: "job1", image: image(5, { prompt: "a lighthouse" }) }),
  );
  act(() => FakeSource.last!.emit("job", job({ state: "done", images: [5] })));
  await screen.findByRole("region", { name: "Result" });
  await user.click(screen.getByRole("button", { name: /Save as Template/ })); // action 1
  const dialog = screen.getByRole("dialog", { name: "Save as Template" });
  expect(within(dialog).getByLabelText("Template name")).toHaveValue("a lighthouse");
  await user.click(within(dialog).getByRole("button", { name: "Save" })); // action 2
  expect(calls.find((c) => c.path === "/api/templates/from-image")?.body).toEqual({
    image_id: 5,
    name: "a lighthouse",
    folder: "",
    tags: [],
    seed: "random",
    variable_prompt: false,
  });
  expect(await screen.findByText(`Saved template “${wallpaper.name}”.`)).toBeVisible();
});

it("Ctrl+K finds a template and runs it", async () => {
  const user = userEvent.setup();
  const { calls } = await start({
    "GET /api/templates": () => [wallpaper, logo],
    "POST /api/jobs": () => job(),
  });
  await user.keyboard("{Control>}k{/Control}");
  const dialog = screen.getByRole("dialog", { name: "Run a template" });
  await user.type(within(dialog).getByRole("combobox"), "logo");
  await within(dialog).findByRole("option", { name: /Logo dark/ });
  await user.keyboard("{Enter}");
  expect(calls.find((c) => c.path === "/api/jobs")?.body).toMatchObject({ template: "logo-dark" });
  // the chip for the last template run is on the Generate view
  expect(await screen.findByRole("button", { name: "Run Logo dark" })).toBeVisible();
});

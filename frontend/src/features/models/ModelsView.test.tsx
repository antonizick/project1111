import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "../../App";
import type { ModelInfo, ModelOperation, ModelPlan } from "../../api/types";
import { baseRoutes, createSource, FakeSource, mockApi, models } from "../../test/fakes";
import { formatBytes } from "./ModelsView";

beforeEach(() => {
  sessionStorage.setItem("p11.token", "tok-abcdefghijkl");
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const missing: ModelInfo = {
  ...models[1]!,
  id: "some-lora",
  name: "Some LoRA",
  kind: "lora",
  state: "missing",
  sets: ["optional"],
  size: 2 * 1024 * 1024,
  licence: {
    name: "CreativeML OpenRAIL-M",
    commercial_use: false,
    flags: ["non-commercial"],
    accepted: false,
  },
};

const plan: ModelPlan = {
  target: "some-lora",
  models: ["some-lora"],
  to_fetch: ["some-lora"],
  licences_to_accept: [
    {
      id: "some-lora",
      name: "Some LoRA",
      licence: "CreativeML OpenRAIL-M",
      url: "https://example.invalid/licence",
      commercial_use: false,
      flags: ["non-commercial"],
    },
  ],
  total_bytes: 2 * 1024 * 1024,
  download_bytes: 2 * 1024 * 1024,
};

const operation: ModelOperation = {
  id: "op1",
  kind: "install",
  target: "some-lora",
  state: "running",
  label: "some-lora",
  done: 512 * 1024,
  total: 2 * 1024 * 1024,
  progress: 0.25,
  error: null,
  report: null,
  started_at: "2026-11-03 17:00 CST",
  seconds: 0,
};

async function start(routes = {}) {
  const api = mockApi({ ...baseRoutes(), ...routes });
  render(<App createSource={createSource} />);
  await screen.findByRole("button", { name: "Photoreal" });
  act(() => FakeSource.last!.onopen?.(new Event("open")));
  return api;
}

it("lists models by kind with state, size and licence", async () => {
  const user = userEvent.setup();
  await start({ "GET /api/models": () => [models[0]!, missing] });
  await user.click(screen.getByRole("button", { name: /^Models/ }));
  expect(await screen.findByRole("heading", { name: "Models" })).toBeVisible();
  expect(screen.getByText("Some LoRA")).toBeVisible();
  expect(screen.getByText("Not installed")).toBeVisible();
  expect(screen.getByText(/CreativeML OpenRAIL-M · non-commercial/)).toBeVisible();
});

it("installs a missing model after the licence dialog and shows progress", async () => {
  const user = userEvent.setup();
  const { calls } = await start({
    "GET /api/models": () => [models[0]!, missing],
    "POST /api/models/plan": () => plan,
    "POST /api/models/install": () => operation,
  });
  await user.click(screen.getByRole("button", { name: /^Models/ }));
  await user.click(await screen.findByRole("button", { name: "Install" }));
  const dialog = await screen.findByRole("dialog", { name: "Install some-lora" });
  const install = within(dialog).getByRole("button", { name: "Install" });
  expect(install).toBeDisabled();
  await user.click(within(dialog).getByLabelText(/I have read and accept/));
  await user.click(install);
  const sent = calls.find((c) => c.path === "/api/models/install");
  expect(sent?.body).toEqual({ target: "some-lora", accept_licences: true });
  expect(
    within(await screen.findByRole("region", { name: "Install progress" })).getByText(
      /Installing some-lora/,
    ),
  ).toBeVisible();
  act(() =>
    FakeSource.last!.emit("models", {
      ...operation,
      done: 2 * 1024 * 1024,
      progress: 1,
    }),
  );
  expect(screen.getByText("2 MB of 2 MB")).toBeVisible();
});

it("disables an installed model and verifies it", async () => {
  const user = userEvent.setup();
  const { calls } = await start({
    "GET /api/models": () => [models[0]!],
    "POST /api/models/realvisxl5-lightning/enabled": () => ({
      id: "realvisxl5-lightning",
      enabled: false,
    }),
    "POST /api/models/verify": () => ({ ok: true, models: [models[0]!] }),
  });
  await user.click(screen.getByRole("button", { name: /^Models/ }));
  await user.click(await screen.findByRole("button", { name: "Disable" }));
  expect(calls.find((c) => c.path.endsWith("/enabled"))?.body).toEqual({ enabled: false });
  await user.click(screen.getByRole("button", { name: "Verify" }));
  expect(await screen.findByText(/file verified/)).toBeVisible();
});

it("formats sizes", () => {
  expect(formatBytes(null)).toBe("—");
  expect(formatBytes(512)).toBe("512 B");
  expect(formatBytes(1536)).toBe("1.5 KB");
  expect(formatBytes(14 * 1024 ** 3)).toBe("14 GB");
});

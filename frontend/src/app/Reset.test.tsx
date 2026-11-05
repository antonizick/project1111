import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "../App";
import { baseRoutes, createSource, FakeSource, job, mockApi, Problem } from "../test/fakes";

beforeEach(() => {
  sessionStorage.setItem("p11.token", "tok-abcdefghijkl");
  localStorage.clear();
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

const emit = (type: string, data: unknown) => act(() => FakeSource.last!.emit(type, data));
const openDialog = async () => {
  await userEvent.click(screen.getByRole("button", { name: "Reset Studio: clear all tabs" }));
  return screen.findByRole("dialog", { name: "Reset Studio?" });
};
const confirm = (dialog: HTMLElement) => within(dialog).getByRole("button", { name: "Reset" });
const prompt = () => screen.getByRole("textbox", { name: /prompt/i }) as HTMLTextAreaElement;

it("is the last control in the top bar and changes nothing until confirmed", async () => {
  await start();
  const buttons = within(screen.getByRole("banner")).getAllByRole("button");
  expect(buttons.at(-1)).toHaveAccessibleName("Reset Studio: clear all tabs");
  await userEvent.type(prompt(), "a lighthouse");
  const dialog = await openDialog();
  expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await openDialog();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(prompt().value).toBe("a lighthouse");
});

it("clears the views, stays on the tab, and sends nothing that writes", async () => {
  const api = await start();
  localStorage.setItem("p11.theme", "light");
  localStorage.setItem("p11.slot-memory", '{"t":{}}');
  localStorage.setItem("p11.recent-templates", '["t"]');
  await userEvent.type(prompt(), "a lighthouse");
  const views = screen.getByRole("navigation", { name: "Views" });
  await userEvent.click(within(views).getByRole("button", { name: "Inpaint" }));
  const before = api.calls.length;
  await userEvent.click(confirm(await openDialog()));
  expect(await screen.findByText("Studio reset. Nothing on disk changed.")).toBeVisible();
  expect(within(views).getByRole("button", { name: "Inpaint" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await userEvent.click(within(views).getByRole("button", { name: "Generate" }));
  expect(prompt().value).toBe("");
  expect(api.calls.slice(before).filter((c) => c.method !== "GET")).toEqual([]);
  expect(localStorage.getItem("p11.theme")).toBe("light");
  expect(localStorage.getItem("p11.slot-memory")).toBe('{"t":{}}');
  expect(localStorage.getItem("p11.recent-templates")).toBe('["t"]');
});

it("waits for an unfinished job and enables itself when the job ends", async () => {
  await start();
  emit("job", job({ state: "running" }));
  const dialog = await openDialog();
  expect(within(dialog).getByText(/1 job is still running/)).toBeVisible();
  expect(confirm(dialog)).toBeDisabled();
  emit("job", job({ state: "paused" }));
  expect(confirm(dialog)).toBeDisabled();
  emit("job", job({ state: "done" }));
  await waitFor(() => expect(confirm(dialog)).toBeEnabled());
  expect(within(dialog).queryByText(/still running/)).not.toBeInTheDocument();
});

it("waits while the stream is down", async () => {
  await start();
  const dialog = await openDialog();
  expect(confirm(dialog)).toBeEnabled();
  act(() => FakeSource.last!.onerror?.(new Event("error")));
  expect(within(dialog).getByText(/reconnecting/)).toBeVisible();
  expect(confirm(dialog)).toBeDisabled();
  act(() => FakeSource.last!.onopen?.(new Event("open")));
  expect(confirm(dialog)).toBeEnabled();
});

it("does not stay held by a job that ended or vanished while the stream was down", async () => {
  await start({
    "GET /api/jobs/ended": () => job({ id: "ended", state: "done" }),
    "GET /api/jobs/lost": () =>
      new Problem(404, { code: "job.unknown", message: "No such job.", hint: "" }),
  });
  emit("job", job({ id: "ended", state: "running" }));
  emit("job", job({ id: "lost", state: "running" }));
  act(() => FakeSource.last!.onerror?.(new Event("error")));
  act(() => FakeSource.last!.onopen?.(new Event("open")));
  const dialog = await openDialog();
  await waitFor(() => expect(confirm(dialog)).toBeEnabled());
});

it("keeps holding when the re-read fails for another reason", async () => {
  await start({
    "GET /api/jobs/job1": () =>
      new Problem(500, { code: "http.500", message: "Broken.", hint: "" }),
  });
  emit("job", job({ state: "running" }));
  act(() => FakeSource.last!.onerror?.(new Event("error")));
  act(() => FakeSource.last!.onopen?.(new Event("open")));
  const dialog = await openDialog();
  await new Promise((r) => setTimeout(r, 0));
  expect(confirm(dialog)).toBeDisabled();
});

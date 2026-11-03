import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { launchCode } from "./api/session";

const json = (status: number, body: unknown) => ({
  ok: status < 400,
  status,
  statusText: "",
  json: async () => body,
});

beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState(null, "", "/");
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("redeems the launch code, stores the token and clears the fragment", async () => {
  window.history.replaceState(null, "", "/#launch=code-123456789");
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(json(200, { token: "tok-abcdefghijkl" }))
    .mockResolvedValueOnce(json(200, { ok: true, version: "0.1.0", fake: true }));
  vi.stubGlobal("fetch", fetch);
  render(<App />);
  expect(screen.getByRole("heading", { name: "P11 Studio" })).toBeInTheDocument();
  expect(await screen.findByText(/Session active \(version 0.1.0, fake engine\)/)).toBeVisible();
  expect(window.location.hash).toBe("");
  expect(sessionStorage.getItem("p11.token")).toBe("tok-abcdefghijkl");
  const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("/api/session");
  expect(JSON.parse(init.body as string)).toEqual({ code: "code-123456789" });
  const headers = (fetch.mock.calls[1] as [string, RequestInit])[1].headers as Headers;
  expect(headers.get("authorization")).toBe("Bearer tok-abcdefghijkl");
});

it("explains how to get a session when the code was already used", async () => {
  window.history.replaceState(null, "", "/#launch=used-code-12345");
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(json(401, { code: "http.401", message: "Link used.", hint: "" })),
  );
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Link used. Open P11 Studio with");
});

it("asks for p11 open without a code or token", async () => {
  vi.stubGlobal("fetch", vi.fn());
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("No session.");
});

it("shows a plain error when the service is down", async () => {
  sessionStorage.setItem("p11.token", "tok-abcdefghijkl");
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach");
});

it("parses the launch code from the fragment", () => {
  expect(launchCode("#launch=abc&x=1")).toBe("abc");
  expect(launchCode("")).toBeNull();
});

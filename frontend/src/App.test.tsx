import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";

afterEach(() => vi.unstubAllGlobals());

it("shows the service health", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok", version: "0.1.0" }) }),
  );
  render(<App />);
  expect(screen.getByRole("heading", { name: "P11 Studio" })).toBeInTheDocument();
  expect(await screen.findByText(/Service is ok \(version 0.1.0\)/)).toBeInTheDocument();
});

it("shows a plain error when the service is down", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach");
});

import { cleanup, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const studio = vi.hoisted(() => ({
  web: null as string | null,
}));

vi.mock("./studio", () => ({
  useStudio: () => ({
    state: {
      jobs: {},
      gpu: null,
      currentModel: null,
      system: { web: studio.web, fake: false, engine: { state: "stopped" } },
    },
  }),
}));

async function bar(built: string, web: string | null) {
  vi.stubGlobal("__P11_BUILD__", built);
  vi.resetModules();
  cleanup();
  studio.web = web;
  const { StatusBar } = await import("./StatusBar");
  render(<StatusBar />);
}

describe("the status bar's build id (ADR-0043)", () => {
  it("shows the build this window loaded", async () => {
    await bar("abcd1234", "abcd1234");
    expect(screen.getByText("Build abcd1234")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reload/ })).not.toBeInTheDocument();
  });

  it("offers a reload when the server has a newer build than the window", async () => {
    await bar("abcd1234", "ffff0000");
    expect(screen.getByRole("button", { name: "New build ready: reload" })).toBeInTheDocument();
  });

  it("stays quiet on an unstamped server and in the dev server", async () => {
    await bar("abcd1234", null);
    expect(screen.queryByRole("button", { name: /reload/ })).not.toBeInTheDocument();
    await bar("dev", "ffff0000");
    expect(screen.queryByRole("button", { name: /reload/ })).not.toBeInTheDocument();
  });
});

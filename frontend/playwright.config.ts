import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  webServer: {
    command: "cd .. && uv run p11 serve",
    url: "http://127.0.0.1:8111/healthz",
    reuseExistingServer: true,
  },
  use: { baseURL: "http://127.0.0.1:8111" },
});

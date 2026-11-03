import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

// The e2e Studio runs with the fake engine in throw-away directories, on its own port.
const root = process.env.P11_E2E_ROOT ?? mkdtempSync(join(tmpdir(), "p11-e2e-"));
process.env.P11_E2E_ROOT = root;
const port = 18211;
export const studioEnv: NodeJS.ProcessEnv = {
  ...process.env,
  P11_CONFIG_DIR: join(root, "config"),
  P11_DATA_DIR: join(root, "data"),
  P11_CACHE_DIR: join(root, "cache"),
  P11_PICTURES_DIR: join(root, "pictures"),
  P11_RUNTIME_DIR: join(root, "run"),
  P11_STUDIO_PORT: String(port),
};

export default defineConfig({
  testDir: "e2e",
  webServer: {
    command: "cd .. && uv run p11 serve --fake",
    url: `http://127.0.0.1:${port}/healthz`,
    env: studioEnv as Record<string, string>,
    reuseExistingServer: false,
  },
  use: { baseURL: `http://127.0.0.1:${port}` },
});

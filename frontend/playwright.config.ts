import { createHash } from "node:crypto";
import { mkdtempSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

// The e2e Studio runs with the fake engine in throw-away directories, on its own port.
const root = process.env.P11_E2E_ROOT ?? mkdtempSync(join(tmpdir(), "p11-e2e-"));
process.env.P11_E2E_ROOT = root;
const port = 18211;

// A loopback model server and a one-entry manifest let the Models page install for real without
// the network (Phase 14). The file is not a model; install only checks its size and SHA-256.
const modelBody = Buffer.from("P11 e2e model fixture\n");
const modelPort = 18212;
const modelServer = createServer((req, res) => {
  if (req.url === "/e2e-test-model.safetensors") {
    res.writeHead(200, {
      "content-type": "application/octet-stream",
      "content-length": String(modelBody.length),
    });
    res.end(modelBody);
    return;
  }
  res.writeHead(404);
  res.end();
});
modelServer.on("error", (e) => {
  // Playwright loads this config in its main process and in workers; the first listener wins.
  if ((e as NodeJS.ErrnoException).code !== "EADDRINUSE") throw e;
});
modelServer.listen(modelPort, "127.0.0.1");

const manifest = `schema_version = 1

[[model]]
id = "e2e-test-model"
name = "E2E test model"
kind = "lora"
base = "sdxl"
sets = ["optional"]
source = "e2e fixture (playwright.config.ts)"
notes = "Loopback fixture for the Models page walkthrough (Phase 14)."
files = [{ url = "http://127.0.0.1:${modelPort}/e2e-test-model.safetensors", filename = "e2e-test-model.safetensors", sha256 = "${createHash("sha256").update(modelBody).digest("hex")}", size = ${modelBody.length} }]
licence = { name = "E2E test licence", url = "https://example.invalid/licence", commercial_use = false, flags = ["research-only"] }
`;
writeFileSync(join(root, "manifest.toml"), manifest);

export const studioEnv: NodeJS.ProcessEnv = {
  ...process.env,
  P11_CONFIG_DIR: join(root, "config"),
  P11_DATA_DIR: join(root, "data"),
  P11_CACHE_DIR: join(root, "cache"),
  P11_PICTURES_DIR: join(root, "pictures"),
  P11_RUNTIME_DIR: join(root, "run"),
  P11_STUDIO_PORT: String(port),
  P11_MODEL_MANIFEST: join(root, "manifest.toml"),
  P11_ALLOW_LOOPBACK_MANIFEST: "1",
};

export default defineConfig({
  testDir: "e2e",
  // Every spec shares one Studio and its single FIFO job queue: parallel workers made specs wait
  // behind each other's jobs and time out depending on order (Phase 14/16). One worker is
  // deterministic and still takes about a minute.
  workers: 1,
  webServer: {
    command: "cd .. && uv run p11 serve --fake",
    url: `http://127.0.0.1:${port}/healthz`,
    env: studioEnv as Record<string, string>,
    reuseExistingServer: false,
  },
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    // P11_E2E_BROWSER=/usr/bin/brave runs the specs in Nick's real browser (Phase 17e).
    launchOptions: { executablePath: process.env.P11_E2E_BROWSER || undefined },
  },
});

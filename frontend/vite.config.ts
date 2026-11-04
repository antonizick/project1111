/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // The id of the sources this bundle was built from (src/p11/webbundle.py, ADR-0043).
  define: { __P11_BUILD__: JSON.stringify(process.env.P11_BUILD_ID ?? "dev") },
  build: {
    outDir: fileURLToPath(new URL("../src/p11/web", import.meta.url)),
    emptyOutDir: true,
  },
  server: { proxy: { "/healthz": "http://127.0.0.1:8111" } },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});

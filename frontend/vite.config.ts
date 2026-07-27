/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Target del proxy configurable (VITE_API_PROXY) para cuando el :8000 está
// ocupado; sin tipos de Node en el config.
const proxyTarget =
  (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env?.[
    "VITE_API_PROXY"
  ] ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Mismo origen en dev: sin CORS y la cookie del refresh viaja sola.
      "/api": proxyTarget,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/tests/setup.ts"],
  },
});

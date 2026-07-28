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
  build: {
    rollupOptions: {
      output: {
        // Code-splitting (F9-prep): recharts SOLO lo usa el dashboard del CRM
        // (que ya es lazy) y mantine se separa para cachear entre deploys.
        manualChunks: {
          recharts: ["recharts"],
          mantine: [
            "@mantine/core",
            "@mantine/dates",
            "@mantine/form",
            "@mantine/hooks",
            "@mantine/modals",
            "@mantine/notifications",
            "mantine-datatable",
          ],
        },
      },
    },
  },
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

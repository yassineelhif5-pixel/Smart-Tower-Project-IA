import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// En développement, /api est relayé vers Django : même origine, donc cookie de session et CSRF sans CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
});

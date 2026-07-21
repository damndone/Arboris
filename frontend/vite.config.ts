import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiProxyTarget =
  process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    // Bounded on purpose. Vitest defaults to one worker per core, and each
    // worker is a full jsdom + React environment costing hundreds of MB. On a
    // 12-core / 24 GB machine an unbounded run already sits near the ceiling,
    // and a second concurrent run (or a dev server alongside it) pushes the
    // machine into swap -- a full gate was observed reaching ~40 GB and being
    // killed mid-suite, which reads as a mysterious test failure rather than
    // as memory exhaustion. Four workers keeps the ceiling predictable; the
    // suite is fast enough that the wall-clock cost is small.
    maxWorkers: 4,
    minWorkers: 1
  }
});

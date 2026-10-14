import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiProxyTarget =
  process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";

// The graph engine (React Flow, its d3 helpers, dagre and the lodash it
// requires) changes far less often than the app; keeping it in its own chunk
// lets the browser reuse it across rebuilds and download it in parallel.
// React gets a chunk of its own: otherwise rollup hoists it into the graph
// chunk (its first shared user), and the launcher would preload the graph.
const GRAPH_VENDOR = /[\\/]node_modules[\\/](reactflow|@reactflow|d3-[\w-]+|dagre|graphlib|lodash|zustand|classcat)[\\/]/;
const REACT_VENDOR = /[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom|@remix-run[\\/]router|use-sync-external-store)[\\/]/;

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: (id) => (REACT_VENDOR.test(id) ? "react-vendor" : GRAPH_VENDOR.test(id) ? "graph-vendor" : undefined),
      },
    },
  },
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

/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `process` is provided by Node when Vite loads this config; declared locally
// to avoid pulling @types/node into the browser build's type graph.
declare const process: { env: Record<string, string | undefined> };

// The API runs on :8000; proxy control-plane routes in dev so the dashboard
// can use same-origin relative URLs (and SSE works without CORS preflight).
const API_TARGET = process.env.VITE_API_TARGET ?? "http://localhost:8000";
const proxy = Object.fromEntries(
  ["/jobs", "/metrics", "/healthz", "/findings", "/scans"].map((p) => [
    p,
    { target: API_TARGET, changeOrigin: true },
  ]),
);

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    css: false,
  },
});

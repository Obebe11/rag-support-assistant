/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));

export default defineConfig(({ mode }) => {
  // Ports come from the environment or the root .env file, never from code.
  const env = { ...loadEnv(mode, repoRoot, ""), ...process.env };
  const backendPort = env.BACKEND_PORT ?? "8000";
  const frontendPort = Number(env.FRONTEND_PORT ?? "5173");

  return {
    plugins: [react()],
    envDir: repoRoot,
    server: {
      port: frontendPort,
      strictPort: true,
      proxy: {
        "/api": `http://127.0.0.1:${backendPort}`,
      },
    },
    preview: {
      port: frontendPort,
      strictPort: true,
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      restoreMocks: true,
      unstubGlobals: true,
    },
  };
});

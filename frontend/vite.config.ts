/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { msw } from "msw/vite";
import { defineConfig, loadEnv } from "vite";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
// `~` points at the UI kit adapted from T3 Code, so its files keep their original imports.
const uiKitRoot = fileURLToPath(new URL("./src/t3code", import.meta.url));

export default defineConfig(({ mode }) => {
  // Ports come from the environment or the root .env file, never from code.
  const env = { ...loadEnv(mode, repoRoot, ""), ...process.env };
  const backendPort = env.BACKEND_PORT ?? "8000";
  const frontendPort = Number(env.FRONTEND_PORT ?? "5173");

  return {
    // `msw()` serves the mock service worker in development only; see `src/mocks/browser.ts`.
    plugins: [react(), tailwindcss(), msw()],
    envDir: repoRoot,
    resolve: {
      alias: { "~": uiKitRoot },
    },
    server: {
      port: frontendPort,
      strictPort: true,
      proxy: {
        "/api": `http://127.0.0.1:${backendPort}`,
      },
    },
    build: {
      rolldownOptions: {
        output: {
          // The React runtime and the other dependencies change less often than the app,
          // so they get chunks of their own that stay cached across releases. The admin
          // page is split off separately, by its lazy import in `src/pages/AdminRoute.tsx`.
          codeSplitting: {
            groups: [
              { name: "react", test: /node_modules[\\/](react|react-dom|react-router|scheduler)[\\/]/ },
              { name: "vendor", test: /node_modules[\\/]/ },
            ],
          },
        },
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

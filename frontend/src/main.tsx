import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import { App } from "./App";
import "./t3code/index.css";
import "./styles/app.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("Root element #root is missing.");
}

async function start(container: HTMLElement) {
  // The mock API exists only in development and is off unless VITE_API_MOCKS=true.
  // `import.meta.env.DEV` is a build-time constant, so a production build drops
  // this branch together with the mock modules and the service worker.
  if (import.meta.env.DEV && import.meta.env.VITE_API_MOCKS === "true") {
    const { enableMockApi } = await import("./mocks/browser");
    await enableMockApi();
  }

  createRoot(container).render(
    <StrictMode>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </StrictMode>,
  );
}

void start(root);

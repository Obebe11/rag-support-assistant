/**
 * Starts the mock API in the browser. Loaded only in development and only when
 * `VITE_API_MOCKS=true` (see `main.tsx`); a production build contains neither
 * this module nor the service worker.
 *
 * Scenario flags come from the page address and stay for the browser tab:
 *   ?mock=delivery:fail,health:live,chat:error,latency:600
 * `?mock=reset` returns to the defaults. Values: health demo | live | db-down |
 * crm-failed | offline; delivery success | retry | fail | reject | queued |
 * retrying; chat ok | error | unavailable | offline. A tagged contact email (`+fail2`, `+fail`,
 * `+reject1`, `+reject`) picks the delivery outcome as the real simulated CRM does.
 */
import { handlers, resetMockApi } from "./handlers";
import type { MockScenario } from "./handlers";

const STORAGE_KEY = "handoff-ai:mock-scenario";

function parseScenario(spec: string): Partial<MockScenario> {
  const scenario: Record<string, string | number> = {};
  for (const pair of spec.split(",")) {
    const [key, value] = pair.split(":");
    if (!key || !value) continue;
    if (key === "latency") {
      scenario.latencyMs = Number(value) || 0;
    } else if (key === "health" || key === "delivery" || key === "chat") {
      scenario[key] = value;
    }
  }
  return scenario as Partial<MockScenario>;
}

function readScenario(): Partial<MockScenario> {
  const fromAddress = new URLSearchParams(window.location.search).get("mock");
  try {
    if (fromAddress === "reset") {
      window.sessionStorage.removeItem(STORAGE_KEY);
      return {};
    }
    if (fromAddress) {
      window.sessionStorage.setItem(STORAGE_KEY, fromAddress);
    }
    return parseScenario(window.sessionStorage.getItem(STORAGE_KEY) ?? "");
  } catch {
    return parseScenario(fromAddress ?? "");
  }
}

export async function enableMockApi(): Promise<void> {
  const { network } = await import("virtual:msw");
  resetMockApi(readScenario());
  network.configure({ handlers, onUnhandledFrame: "bypass" });
  await network.enable();
  console.info("Mock API is on: requests to /api are answered in the browser.");
}

import { vi } from "vitest";

import type { HealthResponse } from "../api/client";

export const demoHealth: HealthResponse = {
  status: "ok",
  version: "0.1.0",
  database: "ok",
  providers: {
    llm: { mode: "local", live: false, model: null },
    embeddings: { mode: "local", live: false, model: null },
    crm: { mode: "simulated", live: false },
  },
};

export const liveHealth: HealthResponse = {
  status: "ok",
  version: "0.1.0",
  database: "ok",
  providers: {
    llm: { mode: "openai_compatible", live: true, model: "example-chat-model" },
    embeddings: { mode: "openai_compatible", live: true, model: "example-embedding-model" },
    crm: { mode: "hubspot", live: true },
  },
};

/** Replace `fetch` with a queue of responses; `null` simulates a network failure. */
export function stubHealthResponses(...responses: (HealthResponse | null)[]) {
  const fetchMock = vi.fn<typeof fetch>();
  for (const body of responses) {
    if (body === null) {
      fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    } else {
      fetchMock.mockResolvedValueOnce(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
  }
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

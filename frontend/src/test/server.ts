import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll } from "vitest";

import { handlers, resetMockApi } from "../mocks/handlers";
import type { MockScenario } from "../mocks/handlers";

export const server = setupServer(...handlers);

/**
 * Run the mock API for every test in the calling file. Requests without a
 * handler fail the test, so the UI cannot quietly call an endpoint outside the
 * contract.
 */
export function useMockApi(scenario: Partial<MockScenario> = {}): void {
  beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
  afterEach(() => {
    server.resetHandlers();
    resetMockApi(scenario);
  });
  afterAll(() => server.close());
  resetMockApi(scenario);
}

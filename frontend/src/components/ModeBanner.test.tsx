import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HealthProvider } from "../hooks/useHealth";
import { demoHealth, liveHealth, stubHealthResponses } from "../test/health";
import { describeDemoModes, ModeBanner } from "./ModeBanner";

function renderBanner() {
  return render(
    <HealthProvider>
      <ModeBanner />
    </HealthProvider>,
  );
}

describe("ModeBanner", () => {
  it("labels every local and simulated provider", async () => {
    const fetchMock = stubHealthResponses(demoHealth);

    renderBanner();

    const banner = await screen.findByRole("complementary", { name: "Demo mode" });
    expect(banner).toHaveTextContent("Local answer mode: no LLM is connected.");
    expect(banner).toHaveTextContent("Local search mode: no embedding API is connected.");
    expect(banner).toHaveTextContent("Simulated CRM: inquiries are not sent to a real CRM.");
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(new URL(request.url).pathname).toBe("/api/health");
  });

  it("labels only the providers that are not live", async () => {
    stubHealthResponses({
      ...liveHealth,
      providers: { ...liveHealth.providers, crm: { mode: "simulated", live: false } },
    });

    renderBanner();

    const banner = await screen.findByRole("complementary", { name: "Demo mode" });
    expect(banner).toHaveTextContent("Simulated CRM");
    expect(banner).not.toHaveTextContent("LLM");
    expect(banner).not.toHaveTextContent("embedding");
  });

  it("shows nothing when every provider is live", async () => {
    const fetchMock = stubHealthResponses(liveHealth);

    const { container } = renderBanner();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("reports an unreachable server and retries on request", async () => {
    stubHealthResponses(null, demoHealth);

    renderBanner();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Cannot reach the server");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("complementary", { name: "Demo mode" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reports an unavailable database next to the demo mode label", async () => {
    stubHealthResponses({ ...demoHealth, status: "degraded", database: "unavailable" });

    renderBanner();

    expect(await screen.findByRole("alert")).toHaveTextContent("Database unavailable");
    expect(screen.getByRole("complementary", { name: "Demo mode" })).toBeInTheDocument();
  });
});

describe("describeDemoModes", () => {
  it("returns no notes for live providers", () => {
    expect(describeDemoModes(liveHealth.providers)).toEqual([]);
  });
});

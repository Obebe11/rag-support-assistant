import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CRM_ACCESS_ERROR } from "./mocks/fixtures";
import { setMockScenario } from "./mocks/handlers";
import { renderApp } from "./test/render";
import { useMockApi } from "./test/server";

describe("App routes", () => {
  useMockApi();

  it("shows the chat at /", async () => {
    renderApp("/");

    expect(screen.getByRole("heading", { level: 1, name: "Support chat" })).toBeVisible();
    expect(screen.getByRole("heading", { level: 2, name: "Ask about shipping, returns, or warranty" })).toBeVisible();
    expect(await screen.findByRole("button", { name: "Demo mode" })).toBeVisible();
  });

  it("shows the admin sign-in at /admin and a way back to the chat", async () => {
    renderApp("/admin");

    expect(screen.getByRole("heading", { level: 1, name: "Admin" })).toBeVisible();
    expect(screen.getByLabelText("Admin token")).toBeVisible();
    expect(screen.getByRole("link", { name: "Back to chat" })).toHaveAttribute("href", "/");
    expect(await screen.findByRole("button", { name: "Demo mode" })).toBeVisible();
  });

  it("shows a not-found page for unknown addresses", () => {
    renderApp("/missing");

    expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Go to the chat" })).toHaveAttribute("href", "/");
  });
});

describe("Demo modes", () => {
  useMockApi();

  it("labels local and simulated modes in the sidebar and in the header", async () => {
    const { user } = renderApp("/");

    const status = await screen.findByRole("region", { name: "Demo status" });
    expect(await within(status).findByText("Simulated")).toBeVisible();
    expect(within(status).getAllByText("Local mode")).toHaveLength(2);

    await user.click(await screen.findByRole("button", { name: "Demo mode" }));
    expect(await screen.findByText("Local answer mode: no LLM is connected.")).toBeVisible();
    expect(screen.getByText("Local search mode: no embedding API is connected.")).toBeVisible();
    expect(screen.getByText("Simulated CRM: inquiries are not sent to a real CRM.")).toBeVisible();
  });

  it("shows no demo badge when every provider is live", async () => {
    setMockScenario({ health: "live" });
    renderApp("/");

    const status = await screen.findByRole("region", { name: "Demo status" });
    expect(await within(status).findByText("Connected")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Demo mode" })).not.toBeInTheDocument();
  });

  it("reports an unreachable server and loads again on request", async () => {
    setMockScenario({ health: "offline" });
    const { user } = renderApp("/");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Cannot reach the server");
    expect(screen.queryByRole("button", { name: "Demo mode" })).not.toBeInTheDocument();

    setMockScenario({ health: "demo" });
    await user.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("button", { name: "Demo mode" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reports a failed CRM access check without the technical message", async () => {
    setMockScenario({ health: "crm-failed" });
    const { user } = renderApp("/");

    const status = await screen.findByRole("region", { name: "Demo status" });
    expect(await within(status).findByText("Access failed")).toBeVisible();

    await user.click(await screen.findByRole("button", { name: "CRM access failed" }));
    expect(await screen.findByText(/Confirmed inquiries are saved and stay queued/)).toBeVisible();
    expect(document.body).not.toHaveTextContent(CRM_ACCESS_ERROR);
  });

  it("reports an unavailable database", async () => {
    setMockScenario({ health: "db-down" });
    renderApp("/");

    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
  });
});

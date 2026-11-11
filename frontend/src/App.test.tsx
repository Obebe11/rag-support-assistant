import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";

import { App } from "./App";
import { demoHealth, stubHealthResponses } from "./test/health";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("App routes", () => {
  beforeEach(() => {
    stubHealthResponses(demoHealth);
  });

  it("shows the chat at /", async () => {
    renderAt("/");

    expect(screen.getByRole("heading", { level: 1, name: "Ask Northline Support" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Chat" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("complementary", { name: "Demo mode" })).toBeInTheDocument();
  });

  it("shows administration at /admin", async () => {
    renderAt("/admin");

    expect(screen.getByRole("heading", { level: 1, name: "Administration" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Admin" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Chat" })).not.toHaveAttribute("aria-current");
    expect(await screen.findByRole("complementary", { name: "Demo mode" })).toBeInTheDocument();
  });

  it("shows a not-found page for unknown addresses", async () => {
    renderAt("/missing");

    expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    expect(await screen.findByRole("complementary", { name: "Demo mode" })).toBeInTheDocument();
  });
});

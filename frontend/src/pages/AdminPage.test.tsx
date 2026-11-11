import { screen, waitFor, within } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { CRM_ACCESS_ERROR, CRM_REJECTED_ERROR, CRM_TIMEOUT_ERROR } from "../mocks/fixtures";
import { MOCK_ADMIN_TOKEN, setMockScenario } from "../mocks/handlers";
import { renderApp } from "../test/render";
import { server, useMockApi } from "../test/server";

async function signIn(user: UserEvent, token: string = MOCK_ADMIN_TOKEN) {
  await user.type(screen.getByLabelText("Admin token"), token);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

async function openDocuments(user: UserEvent) {
  await signIn(user);
  return screen.findByRole("table");
}

function rowOf(title: string): HTMLElement {
  const row = screen.getByText(title).closest("tr");
  if (!row) throw new Error(`No table row for ${title}`);
  return row;
}

const markdownFile = (name: string) => new File(["# Title\n\nText."], name, { type: "text/markdown" });

describe("Admin sign-in", () => {
  useMockApi();

  it("asks for a token before sending anything", async () => {
    const { user } = renderApp("/admin");

    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("A token is required");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("explains a rejected token (403)", async () => {
    const { user } = renderApp("/admin");

    await signIn(user, "wrong-token");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Token not accepted");
    expect(alert).toHaveTextContent("ADMIN_API_TOKEN");
    expect(screen.getByLabelText("Admin token")).toBeInvalid();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("explains a missing token (401)", async () => {
    server.use(
      http.get("*/api/admin/documents", () =>
        HttpResponse.json(
          { error: { code: "unauthorized", message: "An admin token is required.", details: [] } },
          { status: 401 },
        ),
      ),
    );
    const { user } = renderApp("/admin");

    await signIn(user, "any-token");

    expect(await screen.findByRole("alert")).toHaveTextContent("A token is required");
  });

  it("opens the documents with a valid token and keeps the token out of browser storage", async () => {
    const { user } = renderApp("/admin");

    const table = await openDocuments(user);

    expect(within(table).getByText("Shipping Policy")).toBeVisible();
    expect(JSON.stringify({ ...window.localStorage })).not.toContain(MOCK_ADMIN_TOKEN);
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain(MOCK_ADMIN_TOKEN);
    expect(document.cookie).not.toContain(MOCK_ADMIN_TOKEN);
    expect(window.location.href).not.toContain(MOCK_ADMIN_TOKEN);
  });

  it("signs out when the server stops accepting the token", async () => {
    const { user } = renderApp("/admin");
    await openDocuments(user);
    server.use(
      http.delete("*/api/admin/documents/:id", () =>
        HttpResponse.json(
          { error: { code: "forbidden", message: "The admin token is not valid.", details: [] } },
          { status: 403 },
        ),
      ),
    );

    await user.click(within(rowOf("Shipping Policy")).getByRole("button", { name: "Delete document Shipping Policy" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete document" }));

    expect(await screen.findByLabelText("Admin token")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("Token not accepted");
  });

  it("signs out on request", async () => {
    const { user } = renderApp("/admin");
    await openDocuments(user);

    await user.click(screen.getByRole("button", { name: "Sign out" }));

    expect(screen.getByLabelText("Admin token")).toHaveValue("");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("Admin documents", () => {
  useMockApi();

  it("lists documents with the active version and the indexing status", async () => {
    const { user } = renderApp("/admin");

    await openDocuments(user);

    const shipping = within(rowOf("Shipping Policy"));
    expect(shipping.getByText("Version 3.0")).toBeVisible();
    expect(shipping.getByText("Indexed")).toBeVisible();

    const failed = within(rowOf("Price list (scan)"));
    expect(failed.getByText("None, not cited yet")).toBeVisible();
    expect(failed.getByText("Indexing failed")).toBeVisible();
    expect(failed.getByText(/The PDF has no text layer/)).toBeVisible();

    // A replacement in progress: the old version stays active until the new one is indexed.
    const returns = within(rowOf("Returns Policy"));
    expect(returns.getByText("Version 2.0")).toBeVisible();
    expect(returns.getByText("Indexing")).toBeVisible();
    expect(returns.getByText("Version 2.1")).toBeVisible();
  });

  it("uploads a Markdown document and follows its indexing", async () => {
    const { user } = renderApp("/admin");
    await openDocuments(user);

    await user.click(screen.getByRole("button", { name: "Upload document" }));
    const dialog = within(await screen.findByRole("dialog"));
    await user.upload(dialog.getByLabelText("File"), markdownFile("holiday-schedule.md"));
    await user.type(dialog.getByLabelText(/^Title/), "Holiday Schedule");
    await user.type(dialog.getByLabelText(/^Version label/), "1.0");
    await user.click(dialog.getByRole("button", { name: "Upload document" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const row = within(rowOf("Holiday Schedule"));
    expect(row.getByText("holiday-schedule.md")).toBeVisible();
    expect(await row.findByText("Indexed")).toBeVisible();
    expect(row.getByText("Version 1.0")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("7 documents");
  });

  it("rejects a file that is not Markdown or PDF before uploading", async () => {
    const { user } = renderApp("/admin");
    await openDocuments(user);
    let uploads = 0;
    server.use(
      http.post("*/api/admin/documents", () => {
        uploads += 1;
        return undefined;
      }),
    );

    await user.click(screen.getByRole("button", { name: "Upload document" }));
    const dialog = within(await screen.findByRole("dialog"));
    await user.click(dialog.getByRole("button", { name: "Upload document" }));
    expect(dialog.getByText("Choose a Markdown or PDF file.")).toBeVisible();

    const input = dialog.getByLabelText("File");
    await user.upload(input, new File(["a,b"], "prices.csv", { type: "text/csv" }));
    await user.click(dialog.getByRole("button", { name: "Upload document" }));

    expect(dialog.getByText("Use a Markdown (.md) or PDF (.pdf) file.")).toBeVisible();
    expect(uploads).toBe(0);
  });

  it("keeps the dialog open and shows the reason when the server rejects the upload", async () => {
    const { user } = renderApp("/admin");
    await openDocuments(user);
    server.use(
      http.post("*/api/admin/documents", () =>
        HttpResponse.json(
          {
            error: {
              code: "payload_too_large",
              message: "The file is larger than the 10 MB upload limit.",
              details: [],
            },
          },
          { status: 413 },
        ),
      ),
    );

    await user.click(screen.getByRole("button", { name: "Upload document" }));
    const dialog = within(await screen.findByRole("dialog"));
    await user.upload(dialog.getByLabelText("File"), markdownFile("big.md"));
    await user.click(dialog.getByRole("button", { name: "Upload document" }));

    expect(await dialog.findByRole("alert")).toHaveTextContent("The file is larger than the 10 MB upload limit.");
    expect(dialog.getByRole("button", { name: "Upload document" })).toBeEnabled();
  });

  it("replaces a document with a new version", async () => {
    const { user } = renderApp("/admin");
    await openDocuments(user);

    await user.click(within(rowOf("Shipping Policy")).getByRole("button", { name: "Replace document Shipping Policy" }));
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByRole("heading", { name: "Replace “Shipping Policy”" })).toBeVisible();
    expect(dialog.queryByLabelText(/^Title/)).not.toBeInTheDocument();
    await user.upload(dialog.getByLabelText("File"), markdownFile("shipping-policy-3.1.md"));
    await user.type(dialog.getByLabelText(/^Version label/), "3.1");
    await user.click(dialog.getByRole("button", { name: "Upload new version" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const row = within(rowOf("Shipping Policy"));
    expect(row.getByText("shipping-policy-3.1.md")).toBeVisible();
    // After indexing the new version becomes the active one.
    await waitFor(() => expect(row.getByText("Version 3.1")).toBeVisible());
    expect(await row.findByText("Indexed")).toBeVisible();
  });

  it("deletes a document only after confirmation", async () => {
    const { user } = renderApp("/admin");
    await openDocuments(user);

    await user.click(within(rowOf("Warranty Policy")).getByRole("button", { name: "Delete document Warranty Policy" }));
    let dialog = within(await screen.findByRole("alertdialog"));
    expect(dialog.getByRole("heading", { name: "Delete “Warranty Policy”?" })).toBeVisible();
    await user.click(dialog.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(screen.getByText("Warranty Policy")).toBeVisible();

    await user.click(within(rowOf("Warranty Policy")).getByRole("button", { name: "Delete document Warranty Policy" }));
    dialog = within(await screen.findByRole("alertdialog"));
    await user.click(dialog.getByRole("button", { name: "Delete document" }));

    await waitFor(() => expect(screen.queryByText("Warranty Policy")).not.toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent("5 documents");
  });

  it("shows the versions of a document", async () => {
    const { user } = renderApp("/admin");
    await openDocuments(user);

    await user.click(within(rowOf("Shipping Policy")).getByRole("button", { name: "Versions of Shipping Policy" }));

    const panel = within(await screen.findByRole("complementary", { name: "Document versions" }));
    expect(await panel.findByRole("heading", { name: "Version 3.0" })).toBeVisible();
    expect(panel.getByText("Active")).toBeVisible();
    expect(panel.getByRole("heading", { name: "Version 2.2" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Close side panel" }));
    expect(screen.queryByRole("complementary", { name: "Document versions" })).not.toBeInTheDocument();
  });

  it("offers a retry when the list cannot be loaded", async () => {
    const { user } = renderApp("/admin");
    await signIn(user);
    await screen.findByRole("table");
    server.use(
      http.get("*/api/admin/inquiries", () =>
        HttpResponse.json({ error: { code: "internal_error", message: "Boom", details: [] } }, { status: 500 }),
      ),
    );

    await user.click(screen.getByRole("button", { name: "Sign out" }));
    await signIn(user);
    await user.click(await screen.findByRole("tab", { name: "Inquiries" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The server could not complete the request");
    server.resetHandlers();
    await user.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Marcus Oyelaran")).toBeVisible();
  });
});

describe("Admin inquiries", () => {
  useMockApi();

  async function openInquiries(user: UserEvent) {
    await signIn(user);
    await user.click(await screen.findByRole("tab", { name: "Inquiries" }));
    await screen.findByText("Marcus Oyelaran");
  }

  it("lists inquiries with the delivery status and the technical error", async () => {
    const { user } = renderApp("/admin");

    await openInquiries(user);

    const delivered = within(rowOf("Dana Whitfield"));
    expect(delivered.getByText("Purchase")).toBeVisible();
    expect(delivered.getByText("Delivery simulated")).toBeVisible();
    expect(delivered.queryByText("Delivered")).not.toBeInTheDocument();

    const failed = within(rowOf("Marcus Oyelaran"));
    expect(failed.getByText("Human handoff")).toBeVisible();
    expect(failed.getByText("Simulated delivery failed")).toBeVisible();
    expect(failed.getByText("3 attempts, simulated CRM")).toBeVisible();
    expect(failed.getByText(/No automatic attempt is left/)).toBeVisible();
    expect(failed.getByText(CRM_TIMEOUT_ERROR)).toBeVisible();

    const retrying = within(rowOf("Priya Raman"));
    expect(retrying.getByText("Retrying")).toBeVisible();
    expect(retrying.getByText(CRM_TIMEOUT_ERROR)).toBeVisible();

    const rejected = within(rowOf("Tomas Eklund"));
    expect(rejected.getByText(/The CRM rejected the request\. A retry fails the same way/)).toBeVisible();
    expect(rejected.getByText(CRM_REJECTED_ERROR)).toBeVisible();

    expect(screen.getByText("Not confirmed")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("5 inquiries");
  });

  it("shows the attempt log of a delivery", async () => {
    const { user } = renderApp("/admin");
    await openInquiries(user);

    await user.click(within(rowOf("Marcus Oyelaran")).getByRole("button", { name: /Delivery log/ }));

    const panel = within(await screen.findByRole("complementary", { name: "Delivery log" }));
    expect(panel.getByText("Simulated CRM. No CRM record exists.")).toBeVisible();
    expect(panel.getByText("Attempt 1")).toBeVisible();
    expect(panel.getByText("Attempt 3")).toBeVisible();
    expect(panel.getAllByText("Failed")).toHaveLength(3);
    expect(panel.getAllByText(CRM_TIMEOUT_ERROR).length).toBeGreaterThanOrEqual(3);
  });

  it("shows the result of a failed CRM access check", async () => {
    setMockScenario({ health: "crm-failed" });
    const { user } = renderApp("/admin");

    await signIn(user);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("CRM access check failed");
    expect(alert).toHaveTextContent(CRM_ACCESS_ERROR);
  });
});

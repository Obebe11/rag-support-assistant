import { screen, waitFor, within } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { CRM_REJECTED_ERROR, CRM_TIMEOUT_ERROR } from "../../mocks/fixtures";
import { setMockScenario } from "../../mocks/handlers";
import { renderApp } from "../../test/render";
import { server, useMockApi } from "../../test/server";

async function ask(user: UserEvent, question: string) {
  await user.type(screen.getByRole("textbox", { name: "Message" }), `${question}{Enter}`);
}

const conversation = () => screen.getByRole("log", { name: "Conversation" });
const panel = () => within(screen.getByRole("tabpanel"));

/** Ask for a purchase; beside the chat the inquiry form opens in the panel. */
async function startPurchase(user: UserEvent) {
  await ask(user, "I want to buy 20 P-240 printers");
  await screen.findByRole("tabpanel");
  await panel().findByRole("heading", { name: "Purchase inquiry" });
}

async function fillRequired(user: UserEvent) {
  await user.type(panel().getByLabelText("Timeline"), "Within 4 weeks");
  await user.type(panel().getByLabelText("Name"), "Dana Whitfield");
  await user.type(panel().getByLabelText("Email"), "dana.whitfield@example.com");
}

async function reviewPurchase(user: UserEvent) {
  await startPurchase(user);
  await fillRequired(user);
  await user.click(panel().getByRole("button", { name: "Review inquiry" }));
  await panel().findByRole("heading", { name: "Review your inquiry" });
}

/** Count requests to a route without changing what the mock API answers. */
function countRequests(method: "post" | "patch", path: string) {
  const counter = { count: 0 };
  server.use(
    http[method](path, () => {
      counter.count += 1;
      return undefined;
    }),
  );
  return counter;
}

describe("Purchase inquiry", () => {
  useMockApi();

  it("offers a form filled in from the inquiry in the assistant message", async () => {
    const { user } = renderApp("/");

    await startPurchase(user);

    expect(panel().getByLabelText("Product")).toHaveValue("Northline P-240 Monochrome Laser Printer");
    expect(panel().getByLabelText("Quantity")).toHaveValue("20");
    expect(panel().getByLabelText("Timeline")).toHaveValue("");
    expect(panel().getByLabelText("Name")).toHaveValue("");

    const card = within(conversation());
    expect(card.getByRole("heading", { name: "Purchase inquiry" })).toBeVisible();
    expect(card.getByText("Draft")).toBeVisible();
    expect(card.getByText("Still needed: timeline, name, email.")).toBeVisible();
  });

  it("marks the required fields that are empty and moves focus to the first one", async () => {
    const { user } = renderApp("/");
    await startPurchase(user);
    const saves = countRequests("patch", "*/api/inquiries/:id");

    await user.click(panel().getByRole("button", { name: "Review inquiry" }));

    const timeline = panel().getByLabelText("Timeline");
    expect(timeline).toBeInvalid();
    expect(timeline).toHaveAccessibleDescription(expect.stringContaining("Enter when you need the order."));
    expect(panel().getByLabelText("Name")).toHaveAccessibleDescription("Enter your name.");
    expect(panel().getByLabelText("Email")).toHaveAccessibleDescription("Enter your email address.");
    await waitFor(() => expect(timeline).toHaveFocus());
    expect(saves.count).toBe(0);
    expect(panel().getByRole("heading", { name: "Purchase inquiry" })).toBeVisible();

    // Typing in a field clears its error.
    await user.type(timeline, "Soon");
    expect(timeline).toBeValid();
  });

  it("validates the values by the contract before saving", async () => {
    const { user } = renderApp("/");
    await startPurchase(user);
    await fillRequired(user);

    await user.clear(panel().getByLabelText("Quantity"));
    await user.type(panel().getByLabelText("Quantity"), "0");
    await user.clear(panel().getByLabelText("Email"));
    await user.type(panel().getByLabelText("Email"), "dana@");
    await user.click(panel().getByRole("button", { name: "Review inquiry" }));

    expect(panel().getByLabelText("Quantity")).toHaveAccessibleDescription("Enter a whole number of 1 or more.");
    expect(panel().getByLabelText("Email")).toHaveAccessibleDescription(
      "Enter an email address like name@company.com.",
    );
  });

  it("shows the fields the server still reports as missing", async () => {
    const { user } = renderApp("/");
    await startPurchase(user);
    await fillRequired(user);
    server.use(
      http.patch("*/api/inquiries/:id", async ({ request, params }) => {
        const body = (await request.json()) as { product: string; quantity: number; contact: object };
        return HttpResponse.json({
          id: String(params.id),
          conversation_id: null,
          status: "draft",
          kind: "purchase",
          product: body.product,
          quantity: body.quantity,
          timeline: null,
          contact: { name: "Dana Whitfield", email: "dana.whitfield@example.com", company: null, phone: null },
          notes: null,
          missing_fields: ["timeline"],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        });
      }),
    );

    await user.click(panel().getByRole("button", { name: "Review inquiry" }));

    await waitFor(() => expect(panel().getByLabelText("Timeline")).toBeInvalid());
    expect(panel().getByRole("heading", { name: "Purchase inquiry" })).toBeVisible();
    expect(panel().queryByRole("button", { name: "Confirm and send" })).not.toBeInTheDocument();
  });

  it("puts a validation error from the server on its field", async () => {
    const { user } = renderApp("/");
    await startPurchase(user);
    await fillRequired(user);
    server.use(
      http.patch("*/api/inquiries/:id", () =>
        HttpResponse.json(
          {
            error: {
              code: "validation_error",
              message: "The request is not valid.",
              details: [{ field: "body.contact.email", message: "This email domain is not accepted." }],
            },
          },
          { status: 422 },
        ),
      ),
    );

    await user.click(panel().getByRole("button", { name: "Review inquiry" }));

    await waitFor(() =>
      expect(panel().getByLabelText("Email")).toHaveAccessibleDescription("This email domain is not accepted."),
    );
  });

  it("shows a preview of the stored inquiry and sends nothing before confirmation", async () => {
    const { user } = renderApp("/");
    const confirmations = countRequests("post", "*/api/inquiries/:id/confirm");

    await reviewPurchase(user);

    const preview = panel();
    expect(preview.getByText("Nothing is sent until you confirm.")).toBeVisible();
    expect(preview.getByText("Northline P-240 Monochrome Laser Printer")).toBeVisible();
    expect(preview.getByText("Within 4 weeks")).toBeVisible();
    expect(preview.getByText("Dana Whitfield")).toBeVisible();
    expect(preview.getByText("dana.whitfield@example.com")).toBeVisible();
    expect(preview.getByText("Delivery is simulated")).toBeVisible();
    expect(confirmations.count).toBe(0);
    expect(within(conversation()).getByText("Ready to confirm")).toBeVisible();

    await user.click(preview.getByRole("button", { name: "Edit details" }));

    expect(panel().getByLabelText("Name")).toHaveValue("Dana Whitfield");
    expect(confirmations.count).toBe(0);
  });

  it("confirms once, follows the delivery and labels it as simulated", async () => {
    const { user } = renderApp("/");
    const confirmations = countRequests("post", "*/api/inquiries/:id/confirm");
    await reviewPurchase(user);

    // A double click must not confirm twice.
    await user.dblClick(panel().getByRole("button", { name: "Confirm and send" }));

    expect(await panel().findByRole("heading", { name: "Delivery status" })).toBeVisible();
    const status = await panel().findByText("Delivery simulated");
    expect(status).toBeVisible();
    expect(
      panel().getByText(/no CRM is connected, so no CRM record was created and nobody receives this inquiry/),
    ).toBeVisible();
    expect(confirmations.count).toBe(1);
    expect(panel().queryByRole("button", { name: "Confirm and send" })).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("recorded in the Northline CRM");

    // The card in the conversation shows the same status.
    expect(within(conversation()).getByText("Delivery simulated")).toBeVisible();
    expect(within(conversation()).getByRole("button", { name: "View delivery status" })).toBeVisible();
  });

  it("reports a delivery to a live CRM as delivered", async () => {
    setMockScenario({ health: "live" });
    const { user } = renderApp("/");
    await reviewPurchase(user);
    expect(panel().queryByText("Delivery is simulated")).not.toBeInTheDocument();

    await user.click(panel().getByRole("button", { name: "Confirm and send" }));

    expect(await panel().findByText("Delivered")).toBeVisible();
    expect(panel().getByText("Your inquiry is recorded in the Northline CRM.")).toBeVisible();
    expect(document.body).not.toHaveTextContent(/simulated/i);
  });

  it("shows an automatic retry in progress", async () => {
    setMockScenario({ delivery: "retrying" });
    const { user } = renderApp("/");
    await reviewPurchase(user);

    await user.click(panel().getByRole("button", { name: "Confirm and send" }));

    expect(await panel().findByText("Retrying")).toBeVisible();
    expect(panel().getByText(/The next attempt starts automatically\./)).toBeVisible();
    expect(panel().queryByRole("button", { name: "Send again" })).not.toBeInTheDocument();
    // The technical error text is for the admin view only.
    expect(document.body).not.toHaveTextContent(CRM_TIMEOUT_ERROR);
  });

  it("shows a failed delivery with its error and sends again on request", async () => {
    setMockScenario({ delivery: "fail" });
    const { user } = renderApp("/");
    const retries = countRequests("post", "*/api/inquiries/:id/delivery/retry");
    await reviewPurchase(user);

    await user.click(panel().getByRole("button", { name: "Confirm and send" }));

    expect(await panel().findByText("Simulated delivery failed")).toBeVisible();
    expect(
      panel().getByText("Your inquiry is saved, but it was not delivered after 3 attempts. You can send it again."),
    ).toBeVisible();
    expect(within(conversation()).getByText("Simulated delivery failed")).toBeVisible();
    // The technical error text is for the admin view only.
    expect(document.body).not.toHaveTextContent(CRM_TIMEOUT_ERROR);

    await user.dblClick(panel().getByRole("button", { name: "Send again" }));

    expect(await panel().findByText("Delivery simulated")).toBeVisible();
    expect(retries.count).toBe(1);
    expect(panel().queryByRole("button", { name: "Send again" })).not.toBeInTheDocument();
  });

  it("explains a delivery the CRM rejected without the technical error", async () => {
    setMockScenario({ health: "live", delivery: "reject" });
    const { user } = renderApp("/");
    await reviewPurchase(user);

    await user.click(panel().getByRole("button", { name: "Confirm and send" }));

    expect(await panel().findByText("Not delivered")).toBeVisible();
    expect(panel().getByText(/it may fail the same way until the problem is fixed on our side/)).toBeVisible();
    expect(panel().getByRole("button", { name: "Send again" })).toBeVisible();
    expect(document.body).not.toHaveTextContent(CRM_REJECTED_ERROR);
  });

  it("follows the email tags of the simulated CRM", async () => {
    const { user } = renderApp("/");
    await startPurchase(user);
    await user.type(panel().getByLabelText("Timeline"), "Within 4 weeks");
    await user.type(panel().getByLabelText("Name"), "Dana Whitfield");
    await user.type(panel().getByLabelText("Email"), "dana+fail@example.com");
    await user.click(panel().getByRole("button", { name: "Review inquiry" }));
    await user.click(await panel().findByRole("button", { name: "Confirm and send" }));

    expect(await panel().findByText("Simulated delivery failed")).toBeVisible();
  });

  it("returns to the form when the server finds the inquiry incomplete on confirmation", async () => {
    const { user } = renderApp("/");
    await reviewPurchase(user);
    server.use(
      http.post("*/api/inquiries/:id/confirm", () =>
        HttpResponse.json(
          {
            error: {
              code: "validation_error",
              message: "The inquiry is incomplete. Fill in the missing fields before confirming.",
              details: [{ field: "timeline", message: "This field is required." }],
            },
          },
          { status: 422 },
        ),
      ),
    );

    await user.click(panel().getByRole("button", { name: "Confirm and send" }));

    expect(await panel().findByRole("heading", { name: "Purchase inquiry" })).toBeVisible();
    expect(panel().getByLabelText("Timeline")).toHaveAccessibleDescription(
      expect.stringContaining("Enter when you need the order."),
    );
  });

  it("shows the delivery status when the inquiry was already confirmed elsewhere", async () => {
    const { user } = renderApp("/");
    await reviewPurchase(user);
    // Another tab changed the draft: saving answers 409 and the server state wins.
    server.use(
      http.post("*/api/inquiries/:id/confirm", () =>
        HttpResponse.json(
          { error: { code: "conflict", message: "The inquiry is in another state.", details: [] } },
          { status: 409 },
        ),
      ),
      http.get("*/api/inquiries/:id", ({ params }) =>
        HttpResponse.json({
          id: String(params.id),
          status: "confirmed",
          kind: "purchase",
          product: "Northline P-240 Monochrome Laser Printer",
          quantity: 20,
          timeline: "Within 4 weeks",
          contact: { name: "Dana Whitfield", email: "dana.whitfield@example.com", company: null, phone: null },
          notes: null,
          missing_fields: [],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          delivery: {
            status: "delivered",
            crm_mode: "simulated",
            live: false,
            attempt_count: 1,
            attempts: [],
          },
        }),
      ),
    );

    await user.click(panel().getByRole("button", { name: "Confirm and send" }));

    expect(await panel().findByText("Delivery simulated")).toBeVisible();
    expect(panel().queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps the preview and explains when confirmation fails", async () => {
    const { user } = renderApp("/");
    await reviewPurchase(user);
    server.use(
      http.post("*/api/inquiries/:id/confirm", () =>
        HttpResponse.json({ error: { code: "internal_error", message: "Boom", details: [] } }, { status: 500 }),
      ),
    );

    await user.click(panel().getByRole("button", { name: "Confirm and send" }));

    expect(await panel().findByRole("alert")).toHaveTextContent("The server could not complete the request");
    expect(panel().getByRole("button", { name: "Confirm and send" })).toBeEnabled();
  });
});

describe("Human handoff", () => {
  useMockApi();

  async function openHandoff(user: UserEvent) {
    await ask(user, "Do you sell standing desks in walnut?");
    await user.click(await within(conversation()).findByRole("button", { name: "Talk to a person" }));
    await screen.findByRole("tabpanel");
    await panel().findByRole("heading", { name: "Talk to a person" });
  }

  it("admits the knowledge gap and offers a person instead of an answer", async () => {
    const { user } = renderApp("/");

    await ask(user, "Do you sell standing desks in walnut?");

    const log = within(conversation());
    expect(await log.findByText(/I could not find an answer to that in the company's documents/)).toBeVisible();
    expect(log.getByRole("button", { name: "Talk to a person" })).toBeVisible();
    expect(log.queryByRole("region", { name: "Sources" })).not.toBeInTheDocument();
    // The panel stays closed until the visitor asks for a person.
    expect(screen.queryByRole("tabpanel")).not.toBeInTheDocument();
  });

  it("opens a form with the visitor's question and without the purchase fields", async () => {
    const { user } = renderApp("/");

    await openHandoff(user);

    expect(panel().getByLabelText("Your question")).toHaveValue("Do you sell standing desks in walnut?");
    expect(panel().getByLabelText("Name")).toBeVisible();
    expect(panel().getByLabelText("Email")).toBeVisible();
    expect(panel().queryByLabelText("Product")).not.toBeInTheDocument();
    expect(panel().queryByLabelText("Quantity")).not.toBeInTheDocument();
    expect(panel().queryByLabelText("Timeline")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Talk to a person" })).toHaveAttribute("aria-selected", "true");
  });

  it("requires the question, the name and the email", async () => {
    const { user } = renderApp("/");
    await openHandoff(user);
    const creations = countRequests("post", "*/api/inquiries");

    await user.clear(panel().getByLabelText("Your question"));
    await user.click(panel().getByRole("button", { name: "Review request" }));

    expect(panel().getByLabelText("Your question")).toHaveAccessibleDescription("Enter your question.");
    expect(panel().getByLabelText("Name")).toHaveAccessibleDescription("Enter your name.");
    expect(panel().getByLabelText("Email")).toHaveAccessibleDescription("Enter your email address.");
    expect(creations.count).toBe(0);
  });

  it("creates a handoff inquiry, previews it, and delivers it after confirmation", async () => {
    const { user } = renderApp("/");
    await openHandoff(user);
    let created: Record<string, unknown> | null = null;
    server.use(
      http.post("*/api/inquiries", async ({ request }) => {
        created = (await request.clone().json()) as Record<string, unknown>;
        return undefined;
      }),
    );

    await user.type(panel().getByLabelText("Name"), "Marcus Oyelaran");
    await user.type(panel().getByLabelText("Email"), "marcus@example.org");
    await user.click(panel().getByRole("button", { name: "Review request" }));

    expect(await panel().findByRole("heading", { name: "Review your request" })).toBeVisible();
    expect(created).toMatchObject({
      kind: "handoff",
      notes: "Do you sell standing desks in walnut?",
      contact: { name: "Marcus Oyelaran", email: "marcus@example.org", company: null, phone: null },
    });
    expect(created).not.toHaveProperty("product");
    expect(created).not.toHaveProperty("quantity");
    expect(created).not.toHaveProperty("timeline");
    expect(panel().getByText("Do you sell standing desks in walnut?")).toBeVisible();
    expect(panel().getByText("Marcus Oyelaran")).toBeVisible();

    await user.click(panel().getByRole("button", { name: "Confirm and send" }));

    expect(await panel().findByText("Delivery simulated")).toBeVisible();
    expect(panel().getByText(/nobody receives this request/)).toBeVisible();
    expect(within(conversation()).getByRole("heading", { name: "Question for the Northline team" })).toBeVisible();
    expect(within(conversation()).getByText("Delivery simulated")).toBeVisible();
  });
});

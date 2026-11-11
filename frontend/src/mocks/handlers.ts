/**
 * Mock API: MSW handlers that implement the contract in `docs/openapi.json`
 * with an in-memory state. Used by `pnpm dev:mock` and by the tests; it is
 * never part of a production build.
 *
 * The mock keeps the behavior the UI depends on (required fields by inquiry
 * kind, delivery progress, admin token checks) and nothing else. It is not a
 * model of the real backend's retrieval or CRM logic.
 */
import { delay, http, HttpResponse } from "msw";

import type {
  DeliveryRead,
  DocumentDetail,
  DocumentVersionRead,
  ErrorCode,
  ErrorDetail,
  HealthResponse,
  InquiryCreate,
  InquiryField,
  InquiryRead,
  InquiryUpdate,
  MessageRead,
} from "../api/client";
import {
  adminInquiryFixtures,
  clarificationReply,
  crmAccessFailedHealth,
  databaseDownHealth,
  deliveryDelivered,
  deliveryFailed,
  deliveryInProgress,
  deliveryQueued,
  deliveryRejected,
  deliveryRetrying,
  demoHealth,
  documentFixtures,
  groundedReturnsReply,
  groundedShippingReply,
  groundedWarrantyReply,
  inquiryFixture,
  inquiryOfferReply,
  knowledgeGapReply,
  liveHealth,
  nextId,
  refusalReply,
  userMessage,
  versionFixture,
} from "./fixtures";

/** The admin token the mock accepts. */
export const MOCK_ADMIN_TOKEN = "demo-admin-token";

type DeliveryStep = "queued" | "in_progress" | "retrying" | "delivered" | "failed" | "rejected";

const DELIVERY_PLANS = {
  /** Queued, sent, delivered. */
  success: ["queued", "in_progress", "delivered"],
  /** One failed attempt, an automatic retry, then delivered. */
  retry: ["queued", "in_progress", "retrying", "in_progress", "delivered"],
  /** Every automatic attempt fails with a temporary error; a manual retry then succeeds. */
  fail: ["queued", "in_progress", "retrying", "in_progress", "failed"],
  /** The CRM rejects the request: failed at once; a manual retry then succeeds. */
  reject: ["queued", "in_progress", "rejected"],
  /** Stays queued. */
  queued: ["queued"],
  /** Stays in the automatic retry wait. */
  retrying: ["queued", "in_progress", "retrying"],
} as const satisfies Record<string, readonly DeliveryStep[]>;

export interface MockScenario {
  /** What `GET /api/health` reports. `offline` fails every request at the network level. */
  health: "demo" | "live" | "db-down" | "crm-failed" | "offline";
  /** How a confirmed inquiry is delivered. Each status request advances one step. */
  delivery: keyof typeof DELIVERY_PLANS;
  /** `error` answers a chat message with 500; `offline` fails it at the network level. */
  chat: "ok" | "error" | "offline";
  /** Artificial latency per request, in milliseconds. */
  latencyMs: number;
}

const DEFAULT_SCENARIO: MockScenario = { health: "demo", delivery: "success", chat: "ok", latencyMs: 0 };

interface MockDelivery {
  plan: readonly DeliveryStep[];
  step: number;
}

interface MockState {
  scenario: MockScenario;
  conversations: Map<string, { id: string; created_at: string; messages: MessageRead[] }>;
  inquiries: Map<string, InquiryRead>;
  deliveries: Map<string, MockDelivery>;
  documents: DocumentDetail[];
  adminInquiries: InquiryRead[];
}

function freshState(scenario: Partial<MockScenario> = {}): MockState {
  return {
    scenario: { ...DEFAULT_SCENARIO, ...scenario },
    conversations: new Map(),
    inquiries: new Map(),
    deliveries: new Map(),
    documents: documentFixtures(),
    adminInquiries: adminInquiryFixtures(),
  };
}

let state = freshState();

/** Reset the in-memory state; pass scenario flags to change the mock's behavior. */
export function resetMockApi(scenario: Partial<MockScenario> = {}): void {
  state = freshState(scenario);
}

export function setMockScenario(scenario: Partial<MockScenario>): void {
  state.scenario = { ...state.scenario, ...scenario };
}

/** Put an inquiry into the mock state, for example a draft offered by a restored message. */
export function seedMockInquiry(inquiry: InquiryRead): void {
  state.inquiries.set(inquiry.id, inquiry);
}

// --- Helpers ----------------------------------------------------------------

const now = () => new Date().toISOString();

function errorResponse(status: number, code: ErrorCode, message: string, details: ErrorDetail[] = []) {
  return HttpResponse.json({ error: { code, message, details } }, { status });
}

const notFound = (what: string) => errorResponse(404, "not_found", `${what} was not found.`);

function crmIsLive(): boolean {
  return state.scenario.health === "live" || state.scenario.health === "crm-failed";
}

/**
 * The simulated CRM of the real backend fails on purpose for tagged contact
 * emails (see `docs/inquiries.md`). The mock follows the same tags, so a demo
 * script works with and without the backend.
 */
function planForEmail(email: string | null | undefined): keyof typeof DELIVERY_PLANS | null {
  const tag = /\+(fail2|fail|reject1|reject)@/.exec(email ?? "")?.[1];
  switch (tag) {
    case "fail2":
      return "retry";
    case "fail":
      return "fail";
    case "reject1":
    case "reject":
      return "reject";
    default:
      return null;
  }
}

async function pace(): Promise<Response | null> {
  if (state.scenario.latencyMs > 0) {
    await delay(state.scenario.latencyMs);
  }
  return state.scenario.health === "offline" ? HttpResponse.error() : null;
}

function requiredFields(kind: InquiryRead["kind"]): InquiryField[] {
  return kind === "handoff"
    ? ["contact_name", "contact_email", "notes"]
    : ["product", "quantity", "timeline", "contact_name", "contact_email"];
}

function fieldValue(inquiry: InquiryRead, field: InquiryField): unknown {
  switch (field) {
    case "contact_name":
      return inquiry.contact.name;
    case "contact_email":
      return inquiry.contact.email;
    case "contact_company":
      return inquiry.contact.company;
    case "contact_phone":
      return inquiry.contact.phone;
    default:
      return inquiry[field];
  }
}

function withMissingFields(inquiry: InquiryRead): InquiryRead {
  const missing = requiredFields(inquiry.kind).filter((field) => {
    const value = fieldValue(inquiry, field);
    return value === null || value === undefined || value === "";
  });
  return { ...inquiry, missing_fields: missing };
}

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function validateInquiryInput(body: InquiryCreate | InquiryUpdate): ErrorDetail[] {
  const details: ErrorDetail[] = [];
  const email = body.contact?.email;
  if (typeof email === "string" && !EMAIL_PATTERN.test(email.trim())) {
    details.push({ field: "body.contact.email", message: "Enter a valid email address." });
  }
  if (typeof body.quantity === "number" && (!Number.isInteger(body.quantity) || body.quantity < 1)) {
    details.push({ field: "body.quantity", message: "Quantity must be a whole number of at least 1." });
  }
  return details;
}

function applyInquiryInput(inquiry: InquiryRead, body: InquiryCreate | InquiryUpdate): InquiryRead {
  const next: InquiryRead = { ...inquiry, contact: { ...inquiry.contact }, updated_at: now() };
  for (const key of ["product", "timeline", "notes"] as const) {
    if (key in body) next[key] = body[key]?.trim() || null;
  }
  if ("quantity" in body) next.quantity = body.quantity ?? null;
  if (body.contact) {
    for (const key of ["name", "email", "company", "phone"] as const) {
      if (key in body.contact) next.contact[key] = body.contact[key]?.trim() || null;
    }
  }
  return withMissingFields(next);
}

function deliveryAt(delivery: MockDelivery): DeliveryRead {
  const live = crmIsLive();
  const step = delivery.plan[Math.min(delivery.step, delivery.plan.length - 1)];
  const attemptsBefore = delivery.plan
    .slice(0, delivery.step + 1)
    .filter((entry) => entry === "in_progress").length;
  switch (step) {
    case "in_progress":
      return deliveryInProgress(live, attemptsBefore);
    case "retrying":
      return deliveryRetrying(live);
    case "delivered":
      return { ...deliveryDelivered(live), attempt_count: Math.max(attemptsBefore, 1) };
    case "failed":
      return deliveryFailed(live);
    case "rejected":
      return deliveryRejected(live);
    default:
      return deliveryQueued(live);
  }
}

function inquiryWithDelivery(inquiry: InquiryRead): InquiryRead {
  const delivery = state.deliveries.get(inquiry.id);
  return delivery ? { ...inquiry, delivery: deliveryAt(delivery) } : inquiry;
}

/** Pick a reply for a visitor message. The rules exist to reach every answer type by hand. */
function replyTo(content: string, conversationId: string): MessageRead {
  const text = content.toLowerCase();
  let reply: MessageRead;
  if (/ignore (all|your|previous)|system prompt/.test(text)) {
    reply = refusalReply();
  } else if (/\b(buy|order|purchase|quote)\b/.test(text)) {
    const quantity = /\b(\d{1,6})\b/.exec(text);
    const draft = withMissingFields(
      inquiryFixture({
        id: nextId("c3c"),
        conversation_id: conversationId,
        product: /p-?240/.test(text) ? "Northline P-240 Monochrome Laser Printer" : null,
        quantity: quantity ? Number(quantity[1]) : null,
        created_at: now(),
        updated_at: now(),
      }),
    );
    state.inquiries.set(draft.id, draft);
    reply = inquiryOfferReply(draft);
  } else if (/warrant/.test(text)) {
    reply = groundedWarrantyReply();
  } else if (/return|refund/.test(text)) {
    reply = groundedReturnsReply();
  } else if (/ship|deliver|freight/.test(text)) {
    reply = groundedShippingReply();
  } else if (/which|what about|printer\??$/.test(text) || text.length < 12) {
    reply = clarificationReply();
  } else {
    reply = knowledgeGapReply();
  }
  return { ...reply, conversation_id: conversationId, created_at: now() };
}

function checkAdmin(request: Request): Response | null {
  const header = request.headers.get("Authorization");
  if (!header) {
    return errorResponse(401, "unauthorized", "An admin token is required.");
  }
  if (header !== `Bearer ${MOCK_ADMIN_TOKEN}`) {
    return errorResponse(403, "forbidden", "The admin token is not valid.");
  }
  return null;
}

function summary(document: DocumentDetail) {
  const read: Record<string, unknown> = { ...document };
  delete read.versions;
  return read;
}

const MEDIA_TYPES: Record<string, string> = {
  md: "text/markdown",
  markdown: "text/markdown",
  pdf: "application/pdf",
};

async function readUpload(request: Request): Promise<
  | { ok: true; version: (versionNumber: number) => DocumentVersionRead; title: string | null }
  | { ok: false; response: Response }
> {
  const form = await request.formData();
  const file = form.get("file");
  if (!(file instanceof File)) {
    return {
      ok: false,
      response: errorResponse(422, "validation_error", "The request is not valid.", [
        { field: "body.file", message: "A file is required." },
      ]),
    };
  }
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  const mediaType = MEDIA_TYPES[extension];
  if (!mediaType) {
    return {
      ok: false,
      response: errorResponse(
        415,
        "unsupported_media_type",
        "Only Markdown files and PDFs with a text layer are supported.",
      ),
    };
  }
  const label = form.get("version_label");
  const title = form.get("title");
  return {
    ok: true,
    title: typeof title === "string" && title.trim() ? title.trim() : null,
    version: (versionNumber) =>
      versionFixture({
        id: nextId("7a0"),
        version_number: versionNumber,
        version_label: typeof label === "string" && label.trim() ? label.trim() : null,
        source_filename: file.name,
        media_type: mediaType,
        byte_size: file.size,
        is_active: false,
        indexing_status: "pending",
        chunk_count: null,
        page_count: null,
        created_at: now(),
        indexed_at: null,
        activated_at: null,
      }),
  };
}

/** Indexing progresses one step per list request: pending, indexing, ready. */
function advanceIndexing(): void {
  state.documents = state.documents.map((document) => {
    const latest = document.latest_version;
    // The fixture that shows a replacement in progress stays that way.
    if (latest.source_filename === "returns-policy-2.1.md") return document;
    if (latest.indexing_status === "pending") {
      return replaceLatest(document, { ...latest, indexing_status: "indexing" });
    }
    if (latest.indexing_status === "indexing") {
      const ready: DocumentVersionRead = {
        ...latest,
        indexing_status: "ready",
        is_active: true,
        chunk_count: 12,
        indexed_at: now(),
        activated_at: now(),
      };
      const next = replaceLatest(document, ready);
      return {
        ...next,
        active_version: ready,
        versions: next.versions.map((version) =>
          version.id === ready.id ? ready : { ...version, is_active: false },
        ),
      };
    }
    return document;
  });
}

function replaceLatest(document: DocumentDetail, latest: DocumentVersionRead): DocumentDetail {
  return {
    ...document,
    latest_version: latest,
    versions: document.versions.map((version) => (version.id === latest.id ? latest : version)),
  };
}

// --- Handlers ---------------------------------------------------------------

export const handlers = [
  http.get("*/api/health", async () => {
    const failure = await pace();
    if (failure) return failure;
    const bodies: Record<Exclude<MockScenario["health"], "offline">, HealthResponse> = {
      demo: demoHealth,
      live: liveHealth,
      "db-down": databaseDownHealth,
      "crm-failed": crmAccessFailedHealth,
    };
    return HttpResponse.json(bodies[state.scenario.health as keyof typeof bodies]);
  }),

  // Conversations
  http.post("*/api/conversations", async () => {
    const failure = await pace();
    if (failure) return failure;
    const conversation = { id: nextId("d4d"), created_at: now(), messages: [] as MessageRead[] };
    state.conversations.set(conversation.id, conversation);
    return HttpResponse.json({ ...conversation, updated_at: conversation.created_at }, { status: 201 });
  }),

  http.get("*/api/conversations/:id", async ({ params }) => {
    const failure = await pace();
    if (failure) return failure;
    const conversation = state.conversations.get(String(params.id));
    if (!conversation) return notFound("The conversation");
    return HttpResponse.json({
      ...conversation,
      updated_at: conversation.messages.at(-1)?.created_at ?? conversation.created_at,
      messages: conversation.messages.map((message) =>
        message.inquiry
          ? {
              ...message,
              inquiry: inquiryWithDelivery(state.inquiries.get(message.inquiry.id) ?? message.inquiry),
            }
          : message,
      ),
    });
  }),

  http.post("*/api/conversations/:id/messages", async ({ params, request }) => {
    const failure = await pace();
    if (failure) return failure;
    if (state.scenario.chat === "offline") return HttpResponse.error();
    if (state.scenario.chat === "error") {
      return errorResponse(500, "internal_error", "The assistant could not answer. Try again.");
    }
    const conversation = state.conversations.get(String(params.id));
    if (!conversation) return notFound("The conversation");
    const body = (await request.json()) as { content?: unknown };
    const content = typeof body.content === "string" ? body.content.trim() : "";
    if (content.length === 0 || content.length > 4000) {
      return errorResponse(422, "validation_error", "The request is not valid.", [
        { field: "body.content", message: "Enter a message of 1 to 4000 characters." },
      ]);
    }
    const user = userMessage(content, { conversation_id: conversation.id, created_at: now() });
    const assistant = replyTo(content, conversation.id);
    conversation.messages.push(user, assistant);
    return HttpResponse.json({ user_message: user, assistant_message: assistant }, { status: 201 });
  }),

  // Inquiries
  http.post("*/api/inquiries", async ({ request }) => {
    const failure = await pace();
    if (failure) return failure;
    const body = (await request.json()) as InquiryCreate;
    const details = validateInquiryInput(body);
    if (details.length > 0) {
      return errorResponse(422, "validation_error", "The request is not valid.", details);
    }
    const inquiry = applyInquiryInput(
      inquiryFixture({
        id: nextId("c3c"),
        kind: body.kind ?? "purchase",
        conversation_id: body.conversation_id ?? null,
        created_at: now(),
      }),
      body,
    );
    state.inquiries.set(inquiry.id, inquiry);
    return HttpResponse.json(inquiry, { status: 201 });
  }),

  http.get("*/api/inquiries/:id", async ({ params }) => {
    const failure = await pace();
    if (failure) return failure;
    const inquiry = state.inquiries.get(String(params.id));
    return inquiry ? HttpResponse.json(inquiryWithDelivery(inquiry)) : notFound("The inquiry");
  }),

  http.patch("*/api/inquiries/:id", async ({ params, request }) => {
    const failure = await pace();
    if (failure) return failure;
    const inquiry = state.inquiries.get(String(params.id));
    if (!inquiry) return notFound("The inquiry");
    if (inquiry.status !== "draft") {
      return errorResponse(409, "conflict", "A confirmed inquiry cannot be changed.");
    }
    const body = (await request.json()) as InquiryUpdate;
    const details = validateInquiryInput(body);
    if (details.length > 0) {
      return errorResponse(422, "validation_error", "The request is not valid.", details);
    }
    const next = applyInquiryInput(inquiry, body);
    state.inquiries.set(next.id, next);
    return HttpResponse.json(next);
  }),

  http.post("*/api/inquiries/:id/confirm", async ({ params }) => {
    const failure = await pace();
    if (failure) return failure;
    const inquiry = state.inquiries.get(String(params.id));
    if (!inquiry) return notFound("The inquiry");
    // Confirming again returns the same inquiry and queues nothing.
    if (inquiry.status !== "draft") return HttpResponse.json(inquiryWithDelivery(inquiry));
    if (inquiry.missing_fields && inquiry.missing_fields.length > 0) {
      return errorResponse(
        422,
        "validation_error",
        "The inquiry is incomplete. Fill in the missing fields before confirming.",
        inquiry.missing_fields.map((field) => ({ field, message: "This field is required." })),
      );
    }
    const confirmed: InquiryRead = { ...inquiry, status: "confirmed", confirmed_at: now(), updated_at: now() };
    state.inquiries.set(confirmed.id, confirmed);
    const plan = planForEmail(confirmed.contact.email) ?? state.scenario.delivery;
    state.deliveries.set(confirmed.id, { plan: DELIVERY_PLANS[plan], step: 0 });
    return HttpResponse.json(inquiryWithDelivery(confirmed));
  }),

  http.get("*/api/inquiries/:id/delivery", async ({ params }) => {
    const failure = await pace();
    if (failure) return failure;
    const delivery = state.deliveries.get(String(params.id));
    if (!state.inquiries.has(String(params.id))) return notFound("The inquiry");
    if (!delivery) return errorResponse(409, "conflict", "The inquiry is not confirmed yet.");
    delivery.step = Math.min(delivery.step + 1, delivery.plan.length - 1);
    return HttpResponse.json(deliveryAt(delivery));
  }),

  http.post("*/api/inquiries/:id/delivery/retry", async ({ params }) => {
    const failure = await pace();
    if (failure) return failure;
    const delivery = state.deliveries.get(String(params.id));
    if (!state.inquiries.has(String(params.id))) return notFound("The inquiry");
    if (!delivery || deliveryAt(delivery).status !== "failed") {
      return errorResponse(409, "conflict", "Only a failed delivery can be retried.");
    }
    const next: MockDelivery = { plan: DELIVERY_PLANS.success, step: 0 };
    state.deliveries.set(String(params.id), next);
    return HttpResponse.json(deliveryAt(next), { status: 202 });
  }),

  // Admin: documents
  http.get("*/api/admin/documents", async ({ request }) => {
    const failure = (await pace()) ?? checkAdmin(request);
    if (failure) return failure;
    const items = state.documents.map(summary);
    advanceIndexing();
    return HttpResponse.json({ items, total: items.length });
  }),

  http.post("*/api/admin/documents", async ({ request }) => {
    const failure = (await pace()) ?? checkAdmin(request);
    if (failure) return failure;
    const upload = await readUpload(request);
    if (!upload.ok) return upload.response;
    const version = upload.version(1);
    const document: DocumentDetail = {
      id: nextId("6f0"),
      title: upload.title ?? version.source_filename.replace(/\.[^.]+$/, ""),
      created_at: now(),
      updated_at: now(),
      active_version: null,
      latest_version: version,
      versions: [version],
    };
    state.documents = [document, ...state.documents];
    return HttpResponse.json(summary(document), { status: 202 });
  }),

  http.get("*/api/admin/documents/:id", async ({ params, request }) => {
    const failure = (await pace()) ?? checkAdmin(request);
    if (failure) return failure;
    const document = state.documents.find((entry) => entry.id === params.id);
    return document ? HttpResponse.json(document) : notFound("The document");
  }),

  http.post("*/api/admin/documents/:id/versions", async ({ params, request }) => {
    const failure = (await pace()) ?? checkAdmin(request);
    if (failure) return failure;
    const document = state.documents.find((entry) => entry.id === params.id);
    if (!document) return notFound("The document");
    const upload = await readUpload(request);
    if (!upload.ok) return upload.response;
    const version = upload.version(document.versions.length + 1);
    const next: DocumentDetail = {
      ...document,
      updated_at: now(),
      latest_version: version,
      versions: [version, ...document.versions],
    };
    state.documents = state.documents.map((entry) => (entry.id === next.id ? next : entry));
    return HttpResponse.json(summary(next), { status: 202 });
  }),

  http.delete("*/api/admin/documents/:id", async ({ params, request }) => {
    const failure = (await pace()) ?? checkAdmin(request);
    if (failure) return failure;
    if (!state.documents.some((entry) => entry.id === params.id)) return notFound("The document");
    state.documents = state.documents.filter((entry) => entry.id !== params.id);
    return new HttpResponse(null, { status: 204 });
  }),

  // Admin: inquiries
  http.get("*/api/admin/inquiries", async ({ request }) => {
    const failure = (await pace()) ?? checkAdmin(request);
    if (failure) return failure;
    const created = [...state.inquiries.values()].map(inquiryWithDelivery).reverse();
    const items = [...created, ...state.adminInquiries];
    return HttpResponse.json({ items, total: items.length });
  }),
];

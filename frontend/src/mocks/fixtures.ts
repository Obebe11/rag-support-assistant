/**
 * Contract fixtures for the mock API layer and the tests.
 *
 * Every object is typed by the generated schema, so a contract change that
 * breaks a fixture fails the type check. The texts quote the Northline demo
 * knowledge base; Northline Office Equipment is a fictional company.
 */
import type {
  Citation,
  DeliveryRead,
  DocumentDetail,
  DocumentRead,
  DocumentVersionRead,
  HealthResponse,
  InquiryRead,
  MessageRead,
} from "../api/client";

export const CONVERSATION_ID = "0b1f6c1e-5a55-4a5e-9a43-1d5a2b7c9e10";
const NOW = "2026-11-11T10:15:00Z";

// --- Health -----------------------------------------------------------------

export const demoHealth: HealthResponse = {
  status: "ok",
  version: "0.1.0",
  database: "ok",
  providers: {
    llm: { mode: "local", live: false, model: null },
    embeddings: { mode: "local", live: false, model: null },
    crm: {
      mode: "simulated",
      live: false,
      access: {
        state: "ok",
        message: "Simulated CRM: no external account is checked or written to.",
        checked_at: NOW,
      },
    },
  },
};

export const liveHealth: HealthResponse = {
  status: "ok",
  version: "0.1.0",
  database: "ok",
  providers: {
    llm: { mode: "openai_compatible", live: true, model: "example-chat-model" },
    embeddings: { mode: "openai_compatible", live: true, model: "example-embedding-model" },
    crm: {
      mode: "hubspot",
      live: true,
      access: { state: "ok", message: "The CRM account, its permissions and fields were checked.", checked_at: NOW },
    },
  },
};

export const CRM_ACCESS_ERROR = "The CRM rejected the access token (401).";

/** Live providers, but the CRM access check failed: the overall status is degraded. */
export const crmAccessFailedHealth: HealthResponse = {
  ...liveHealth,
  status: "degraded",
  providers: {
    ...liveHealth.providers,
    crm: { mode: "hubspot", live: true, access: { state: "failed", message: CRM_ACCESS_ERROR, checked_at: NOW } },
  },
};

export const databaseDownHealth: HealthResponse = {
  ...demoHealth,
  status: "degraded",
  database: "unavailable",
};

// --- Citations --------------------------------------------------------------

const DOC_SHIPPING = "6f0f3d3c-8a52-4a0b-b6d0-0d6f7a4f1a01";
const DOC_RETURNS = "6f0f3d3c-8a52-4a0b-b6d0-0d6f7a4f1a02";
const DOC_WARRANTY = "6f0f3d3c-8a52-4a0b-b6d0-0d6f7a4f1a03";
const DOC_FAQ = "6f0f3d3c-8a52-4a0b-b6d0-0d6f7a4f1a04";
const DOC_VOLUME = "6f0f3d3c-8a52-4a0b-b6d0-0d6f7a4f1a05";
const DOC_P240 = "6f0f3d3c-8a52-4a0b-b6d0-0d6f7a4f1a06";

export const shippingCitations: Citation[] = [
  {
    document_id: DOC_SHIPPING,
    document_title: "Shipping Policy",
    document_version_id: "7a000000-0000-4000-8000-000000000101",
    version_number: 2,
    version_label: "3.0",
    chunk_id: "8c000000-0000-4000-8000-000000000101",
    page_number: null,
    section: "Shipping and delivery > Parcel shipping methods and rates",
    excerpt:
      "Standard Ground shipping is free when the merchandise subtotal, after any discounts, is $500 or more. Free shipping does not apply to Two-Day Air, Next-Day Air, or orders to Alaska and Hawaii.",
    score: 0.83,
  },
  {
    document_id: DOC_SHIPPING,
    document_title: "Shipping Policy",
    document_version_id: "7a000000-0000-4000-8000-000000000101",
    version_number: 2,
    version_label: "3.0",
    chunk_id: "8c000000-0000-4000-8000-000000000102",
    page_number: null,
    section: "Shipping and delivery > Order processing",
    excerpt:
      "In-stock orders placed by 2:00 p.m. Pacific Time on a business day ship the same day. Orders placed after 2:00 p.m. Pacific Time, on a weekend or on a company holiday ship the next business day.",
    score: 0.71,
  },
  {
    document_id: DOC_FAQ,
    document_title: "Frequently Asked Questions",
    document_version_id: "7a000000-0000-4000-8000-000000000104",
    version_number: 1,
    version_label: "2.3",
    chunk_id: "8c000000-0000-4000-8000-000000000103",
    page_number: null,
    section: "Shipping",
    excerpt:
      "Delivery times are carrier estimates. They are not guaranteed delivery dates.",
    score: 0.64,
  },
];

export const returnsCitations: Citation[] = [
  {
    document_id: DOC_RETURNS,
    document_title: "Returns Policy",
    document_version_id: "7a000000-0000-4000-8000-000000000102",
    version_number: 2,
    version_label: "2.0",
    chunk_id: "8c000000-0000-4000-8000-000000000201",
    page_number: null,
    section: "Returns and refunds > Return window",
    excerpt:
      "You can return most items within 30 days of the delivery date. The delivery date is the date shown in the carrier's tracking record.",
    score: 0.86,
  },
  {
    document_id: DOC_RETURNS,
    document_title: "Returns Policy",
    document_version_id: "7a000000-0000-4000-8000-000000000102",
    version_number: 2,
    version_label: "2.0",
    chunk_id: "8c000000-0000-4000-8000-000000000202",
    page_number: null,
    section: "Returns and refunds > Item condition and refund amount",
    excerpt:
      "Opened, in like-new condition with all accessories, manuals and packaging: item price less a 15% restocking fee.",
    score: 0.74,
  },
];

export const warrantyCitations: Citation[] = [
  {
    document_id: DOC_WARRANTY,
    document_title: "Warranty Policy",
    document_version_id: "7a000000-0000-4000-8000-000000000103",
    version_number: 1,
    version_label: "4.0",
    chunk_id: "8c000000-0000-4000-8000-000000000301",
    page_number: 1,
    section: null,
    excerpt:
      "P-240 Monochrome Laser Printer: 2 years. Every warranty period starts on the delivery date.",
    score: 0.88,
  },
  {
    document_id: DOC_WARRANTY,
    document_title: "Warranty Policy",
    document_version_id: "7a000000-0000-4000-8000-000000000103",
    version_number: 1,
    version_label: null,
    chunk_id: "8c000000-0000-4000-8000-000000000302",
    page_number: 2,
    section: null,
    excerpt:
      "The warranty covers defects in materials and workmanship that appear during the warranty period under normal use, parts and labor for covered repairs, and shipping in both directions.",
    score: 0.69,
  },
];

// --- Messages ---------------------------------------------------------------

let messageCounter = 0;

/** A deterministic UUID-shaped id; unique within one mock session or test. */
export function nextId(prefix: string): string {
  messageCounter += 1;
  return `${prefix}00000-0000-4000-8000-${String(messageCounter).padStart(12, "0")}`;
}

export function userMessage(content: string, overrides: Partial<MessageRead> = {}): MessageRead {
  return {
    id: nextId("a1a"),
    conversation_id: CONVERSATION_ID,
    role: "user",
    content,
    answer_type: null,
    citations: [],
    inquiry: null,
    created_at: NOW,
    ...overrides,
  };
}

export function assistantMessage(overrides: Partial<MessageRead>): MessageRead {
  return {
    id: nextId("b2b"),
    conversation_id: CONVERSATION_ID,
    role: "assistant",
    content: "",
    answer_type: "clarification",
    citations: [],
    inquiry: null,
    created_at: NOW,
    ...overrides,
  };
}

export const groundedShippingReply = (): MessageRead =>
  assistantMessage({
    answer_type: "grounded",
    content:
      "Standard Ground shipping costs $14.95 per order and is free when the merchandise subtotal is $500 or more. In-stock orders placed by 2:00 p.m. Pacific Time on a business day ship the same day.\n\nDelivery takes 3 to 5 business days after shipment. These are carrier estimates, not guaranteed delivery dates.",
    citations: shippingCitations,
  });

export const groundedReturnsReply = (): MessageRead =>
  assistantMessage({
    answer_type: "grounded",
    content:
      "You can return most items within 30 days of the delivery date. An opened item in like-new condition is refunded at the item price less a 15% restocking fee.\n\nEvery return needs a return merchandise authorization (RMA) number.",
    citations: returnsCitations,
  });

export const groundedWarrantyReply = (): MessageRead =>
  assistantMessage({
    answer_type: "grounded",
    content:
      "The P-240 Monochrome Laser Printer has a 2-year warranty that starts on the delivery date. It covers defects in materials and workmanship, including parts, labor and shipping in both directions for covered repairs.",
    citations: warrantyCitations,
  });

export const knowledgeGapReply = (): MessageRead =>
  assistantMessage({
    answer_type: "knowledge_gap",
    content:
      "I could not find this in Northline's documents, so I cannot answer it reliably. A member of the Northline team can help you with this question.",
  });

export const clarificationReply = (): MessageRead =>
  assistantMessage({
    answer_type: "clarification",
    content:
      "Which product do you mean? Northline sells the P-240 laser printer, the C-360 color multifunction printer, the LP-420 label printer, the S-300 shredder and the L-125 laminator.",
  });

export const refusalReply = (): MessageRead =>
  assistantMessage({
    answer_type: "refusal",
    content:
      "I can only help with questions about Northline products, orders and policies. I cannot follow that request.",
  });

// --- Inquiries --------------------------------------------------------------

export function inquiryFixture(overrides: Partial<InquiryRead> = {}): InquiryRead {
  return {
    id: "c3c00000-0000-4000-8000-000000000001",
    conversation_id: CONVERSATION_ID,
    status: "draft",
    kind: "purchase",
    product: null,
    quantity: null,
    timeline: null,
    contact: { name: null, email: null, company: null, phone: null },
    notes: null,
    missing_fields: ["product", "quantity", "timeline", "contact_name", "contact_email"],
    created_at: NOW,
    updated_at: NOW,
    confirmed_at: null,
    delivery: null,
    ...overrides,
  };
}

/** A draft the assistant pre-filled from the conversation; contact details are missing. */
export const offeredDraft = (): InquiryRead =>
  inquiryFixture({
    product: "Northline P-240 Monochrome Laser Printer",
    quantity: 20,
    timeline: null,
    missing_fields: ["timeline", "contact_name", "contact_email"],
  });

export const completeDraft = (): InquiryRead =>
  inquiryFixture({
    product: "Northline P-240 Monochrome Laser Printer",
    quantity: 20,
    timeline: "Within 30 days",
    contact: {
      name: "Dana Whitfield",
      email: "dana.whitfield@example.com",
      company: "Harbor Street Clinic",
      phone: null,
    },
    notes: null,
    missing_fields: [],
  });

export const inquiryOfferReply = (inquiry: InquiryRead | null = offeredDraft()): MessageRead =>
  assistantMessage({
    answer_type: "inquiry_offer",
    content:
      "I can pass this request to the Northline sales team. Review the details below, add your contact information and confirm to send the inquiry.",
    inquiry,
  });

// --- Deliveries -------------------------------------------------------------

export function deliveryFixture(overrides: Partial<DeliveryRead> = {}): DeliveryRead {
  return {
    status: "pending",
    crm_mode: "simulated",
    live: false,
    attempt_count: 0,
    failure_reason: null,
    last_error: null,
    last_attempt_at: null,
    next_attempt_at: null,
    delivered_at: null,
    crm_contact_id: null,
    crm_record_id: null,
    attempts: [],
    ...overrides,
  };
}

export const CRM_TIMEOUT_ERROR = "The CRM did not respond in time (timeout after 10 s).";

export const deliveryQueued = (live = false): DeliveryRead =>
  deliveryFixture({ live, crm_mode: live ? "hubspot" : "simulated" });

export const deliveryInProgress = (live = false, attempt = 1): DeliveryRead =>
  deliveryFixture({
    status: "in_progress",
    live,
    crm_mode: live ? "hubspot" : "simulated",
    attempt_count: attempt,
    last_attempt_at: NOW,
  });

/** Waiting for an automatic retry after a failed attempt. */
export const deliveryRetrying = (live = false): DeliveryRead =>
  deliveryFixture({
    status: "pending",
    live,
    crm_mode: live ? "hubspot" : "simulated",
    attempt_count: 1,
    last_error: CRM_TIMEOUT_ERROR,
    last_attempt_at: NOW,
    next_attempt_at: "2026-11-11T10:15:10Z",
    attempts: [
      {
        attempt_number: 1,
        outcome: "failed",
        error: CRM_TIMEOUT_ERROR,
        started_at: NOW,
        finished_at: NOW,
      },
    ],
  });

export const deliveryDelivered = (live = false): DeliveryRead =>
  deliveryFixture({
    status: "delivered",
    live,
    crm_mode: live ? "hubspot" : "simulated",
    attempt_count: 1,
    last_attempt_at: NOW,
    delivered_at: NOW,
    crm_contact_id: live ? "151" : null,
    crm_record_id: live ? "48120" : null,
    attempts: [
      {
        attempt_number: 1,
        outcome: "succeeded",
        error: null,
        started_at: NOW,
        finished_at: NOW,
      },
    ],
  });

/** No automatic attempt is left: every one hit a temporary error. */
export const deliveryFailed = (live = false): DeliveryRead =>
  deliveryFixture({
    status: "failed",
    live,
    crm_mode: live ? "hubspot" : "simulated",
    attempt_count: 3,
    failure_reason: "attempts_exhausted",
    last_error: CRM_TIMEOUT_ERROR,
    last_attempt_at: NOW,
    attempts: [1, 2, 3].map((attempt_number) => ({
      attempt_number,
      outcome: "failed" as const,
      error: CRM_TIMEOUT_ERROR,
      started_at: NOW,
      finished_at: NOW,
    })),
  });

export const CRM_REJECTED_ERROR = "The CRM rejected the request (403: missing scope).";

/** The CRM rejected the request: failed at once, without automatic retries. */
export const deliveryRejected = (live = false): DeliveryRead =>
  deliveryFixture({
    status: "failed",
    live,
    crm_mode: live ? "hubspot" : "simulated",
    attempt_count: 1,
    failure_reason: "permanent_error",
    last_error: CRM_REJECTED_ERROR,
    last_attempt_at: NOW,
    attempts: [
      { attempt_number: 1, outcome: "failed", error: CRM_REJECTED_ERROR, started_at: NOW, finished_at: NOW },
    ],
  });

// --- Documents --------------------------------------------------------------

export function versionFixture(overrides: Partial<DocumentVersionRead> = {}): DocumentVersionRead {
  return {
    id: "7a000000-0000-4000-8000-000000000101",
    version_number: 1,
    version_label: null,
    source_filename: "document.md",
    media_type: "text/markdown",
    byte_size: 6240,
    checksum_sha256: "9f2c4b7e1d3a5f60718293a4b5c6d7e8f9012a3b4c5d6e7f8091a2b3c4d5e6f7",
    is_active: true,
    indexing_status: "ready",
    indexing_error: null,
    page_count: null,
    chunk_count: 14,
    created_at: "2026-11-10T09:00:00Z",
    indexed_at: "2026-11-10T09:00:20Z",
    activated_at: "2026-11-10T09:00:20Z",
    ...overrides,
  };
}

function documentFixture(
  id: string,
  title: string,
  active: DocumentVersionRead | null,
  latest: DocumentVersionRead,
): DocumentRead {
  return {
    id,
    title,
    created_at: "2026-11-10T09:00:00Z",
    updated_at: latest.created_at,
    active_version: active,
    latest_version: latest,
  };
}

const shippingV1 = versionFixture({
  id: "7a000000-0000-4000-8000-000000000100",
  version_number: 1,
  version_label: "2.2",
  source_filename: "shipping-policy-v2.2.md",
  is_active: false,
  chunk_count: 16,
});
const shippingV2 = versionFixture({
  id: "7a000000-0000-4000-8000-000000000101",
  version_number: 2,
  version_label: "3.0",
  source_filename: "shipping-policy.md",
  byte_size: 7412,
  chunk_count: 18,
  created_at: "2026-11-10T14:30:00Z",
  indexed_at: "2026-11-10T14:30:25Z",
  activated_at: "2026-11-10T14:30:25Z",
});
const returnsV1 = versionFixture({
  id: "7a000000-0000-4000-8000-000000000102",
  version_label: "2.0",
  source_filename: "returns-policy.md",
  byte_size: 5120,
  chunk_count: 11,
});
/** A replacement that is still being indexed: the old version keeps answering. */
const returnsV2 = versionFixture({
  id: "7a000000-0000-4000-8000-000000000112",
  version_number: 2,
  version_label: "2.1",
  source_filename: "returns-policy-2.1.md",
  byte_size: 5388,
  is_active: false,
  indexing_status: "indexing",
  chunk_count: null,
  created_at: "2026-11-11T10:10:00Z",
  indexed_at: null,
  activated_at: null,
});
const warrantyV1 = versionFixture({
  id: "7a000000-0000-4000-8000-000000000103",
  version_label: "4.0",
  source_filename: "warranty-policy.pdf",
  media_type: "application/pdf",
  byte_size: 48213,
  page_count: 3,
  chunk_count: 9,
});
/** A first upload that failed: the document has no active version. */
const scannedV1 = versionFixture({
  id: "7a000000-0000-4000-8000-000000000107",
  source_filename: "price-list-scan.pdf",
  media_type: "application/pdf",
  byte_size: 912004,
  is_active: false,
  indexing_status: "failed",
  indexing_error: "The PDF has no text layer. Upload a PDF with selectable text.",
  page_count: 2,
  chunk_count: null,
  created_at: "2026-11-11T09:40:00Z",
  indexed_at: null,
  activated_at: null,
});
const volumeV1 = versionFixture({
  id: "7a000000-0000-4000-8000-000000000105",
  version_label: "1.2",
  source_filename: "volume-orders-and-quotes.md",
  byte_size: 4310,
  chunk_count: 8,
});
const p240V1 = versionFixture({
  id: "7a000000-0000-4000-8000-000000000106",
  version_label: "1.2",
  source_filename: "product-p240-laser-printer.md",
  byte_size: 3904,
  chunk_count: 7,
});

export function documentFixtures(): DocumentDetail[] {
  return [
    { ...documentFixture(DOC_SHIPPING, "Shipping Policy", shippingV2, shippingV2), versions: [shippingV2, shippingV1] },
    { ...documentFixture(DOC_RETURNS, "Returns Policy", returnsV1, returnsV2), versions: [returnsV2, returnsV1] },
    { ...documentFixture(DOC_WARRANTY, "Warranty Policy", warrantyV1, warrantyV1), versions: [warrantyV1] },
    { ...documentFixture(DOC_VOLUME, "Volume Orders and Quotes", volumeV1, volumeV1), versions: [volumeV1] },
    {
      ...documentFixture(DOC_P240, "Northline P-240 Monochrome Laser Printer", p240V1, p240V1),
      versions: [p240V1],
    },
    {
      ...documentFixture("6f0f3d3c-8a52-4a0b-b6d0-0d6f7a4f1a07", "Price list (scan)", null, scannedV1),
      versions: [scannedV1],
    },
  ];
}

// --- Admin inquiry list -----------------------------------------------------

export function adminInquiryFixtures(): InquiryRead[] {
  return [
    inquiryFixture({
      ...completeDraft(),
      id: "c3c00000-0000-4000-8000-000000000011",
      status: "confirmed",
      confirmed_at: "2026-11-11T09:58:00Z",
      updated_at: "2026-11-11T09:58:00Z",
      delivery: deliveryDelivered(false),
    }),
    inquiryFixture({
      id: "c3c00000-0000-4000-8000-000000000012",
      kind: "handoff",
      status: "confirmed",
      contact: {
        name: "Marcus Oyelaran",
        email: "marcus@example.org",
        company: null,
        phone: "+1 415 555 0142",
      },
      notes: "Do you offer a discount for nonprofit organizations?",
      missing_fields: [],
      confirmed_at: "2026-11-11T09:41:00Z",
      updated_at: "2026-11-11T09:41:00Z",
      delivery: deliveryFailed(false),
    }),
    inquiryFixture({
      id: "c3c00000-0000-4000-8000-000000000013",
      status: "confirmed",
      product: "Northline S-300 Cross-Cut Shredder",
      quantity: 4,
      timeline: "Before December 15",
      contact: {
        name: "Priya Raman",
        email: "priya.raman@example.com",
        company: "Lakeside Legal Partners",
        phone: null,
      },
      notes: "Please include liftgate delivery in the quote.",
      missing_fields: [],
      confirmed_at: "2026-11-11T09:20:00Z",
      updated_at: "2026-11-11T09:20:00Z",
      delivery: deliveryRetrying(false),
    }),
    inquiryFixture({
      id: "c3c00000-0000-4000-8000-000000000015",
      status: "confirmed",
      product: "Northline LP-420 Label Printer",
      quantity: 2,
      timeline: "This month",
      contact: { name: "Tomas Eklund", email: "tomas.eklund@example.com", company: null, phone: null },
      missing_fields: [],
      confirmed_at: "2026-11-11T09:05:00Z",
      updated_at: "2026-11-11T09:05:00Z",
      delivery: deliveryRejected(false),
    }),
    inquiryFixture({ ...offeredDraft(), id: "c3c00000-0000-4000-8000-000000000014" }),
  ];
}

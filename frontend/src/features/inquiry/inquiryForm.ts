/**
 * Inquiry form model: field values, validation by the API contract, and the
 * request bodies. No React here, so the rules are easy to test.
 */
import type {
  ErrorDetail,
  InquiryCreate,
  InquiryField,
  InquiryKind,
  InquiryRead,
  InquiryUpdate,
} from "../../api/client";

/** Form values are strings, as typed; they are converted when the request is built. */
export type InquiryValues = Record<InquiryField, string>;
export type InquiryErrors = Partial<Record<InquiryField, string>>;

export const EMPTY_VALUES: InquiryValues = {
  product: "",
  quantity: "",
  timeline: "",
  contact_name: "",
  contact_email: "",
  contact_company: "",
  contact_phone: "",
  notes: "",
};

/** Fields shown for each kind, in form order. A handoff asks only who to reach and what to answer. */
export const FIELDS_BY_KIND: Record<InquiryKind, InquiryField[]> = {
  purchase: [
    "product",
    "quantity",
    "timeline",
    "contact_name",
    "contact_email",
    "contact_company",
    "contact_phone",
    "notes",
  ],
  handoff: ["notes", "contact_name", "contact_email", "contact_company", "contact_phone"],
};

/** Mirrors `required_inquiry_fields` in the backend contract. */
export const REQUIRED_BY_KIND: Record<InquiryKind, InquiryField[]> = {
  purchase: ["product", "quantity", "timeline", "contact_name", "contact_email"],
  handoff: ["contact_name", "contact_email", "notes"],
};

export const FIELD_LABELS: Record<InquiryKind, Record<InquiryField, string>> = {
  purchase: {
    product: "Product",
    quantity: "Quantity",
    timeline: "Timeline",
    contact_name: "Name",
    contact_email: "Email",
    contact_company: "Company",
    contact_phone: "Phone",
    notes: "Notes",
  },
  handoff: {
    product: "Product",
    quantity: "Quantity",
    timeline: "Timeline",
    contact_name: "Name",
    contact_email: "Email",
    contact_company: "Company",
    contact_phone: "Phone",
    notes: "Your question",
  },
};

/** Length limits from `backend/app/schemas/inquiries.py`. */
export const MAX_LENGTH: Record<InquiryField, number> = {
  product: 500,
  quantity: 7,
  timeline: 200,
  contact_name: 200,
  contact_email: 320,
  contact_company: 200,
  contact_phone: 50,
  notes: 2000,
};

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const MAX_QUANTITY = 1_000_000;

export function valuesFromInquiry(inquiry: InquiryRead | null, defaults: Partial<InquiryValues> = {}): InquiryValues {
  if (inquiry === null) return { ...EMPTY_VALUES, ...defaults };
  return {
    product: inquiry.product ?? defaults.product ?? "",
    quantity: inquiry.quantity != null ? String(inquiry.quantity) : (defaults.quantity ?? ""),
    timeline: inquiry.timeline ?? defaults.timeline ?? "",
    contact_name: inquiry.contact.name ?? defaults.contact_name ?? "",
    contact_email: inquiry.contact.email ?? defaults.contact_email ?? "",
    contact_company: inquiry.contact.company ?? defaults.contact_company ?? "",
    contact_phone: inquiry.contact.phone ?? defaults.contact_phone ?? "",
    notes: inquiry.notes ?? defaults.notes ?? "",
  };
}

function requiredMessage(kind: InquiryKind, field: InquiryField): string {
  switch (field) {
    case "product":
      return "Enter the product you want to buy.";
    case "quantity":
      return "Enter how many units you need.";
    case "timeline":
      return "Enter when you need the order.";
    case "contact_name":
      return "Enter your name.";
    case "contact_email":
      return "Enter your email address.";
    case "notes":
      return kind === "handoff" ? "Enter your question." : "Enter a note.";
    default:
      return "Enter a value.";
  }
}

/** Validate what is shown for this kind; hidden fields are never checked. */
export function validateInquiry(kind: InquiryKind, values: InquiryValues): InquiryErrors {
  const errors: InquiryErrors = {};
  const required = REQUIRED_BY_KIND[kind];
  for (const field of FIELDS_BY_KIND[kind]) {
    const value = values[field].trim();
    if (value === "") {
      if (required.includes(field)) errors[field] = requiredMessage(kind, field);
      continue;
    }
    if (value.length > MAX_LENGTH[field]) {
      errors[field] = `Use ${MAX_LENGTH[field]} characters or fewer.`;
      continue;
    }
    if (field === "quantity") {
      const quantity = Number(value);
      if (!/^\d+$/.test(value) || quantity < 1) {
        errors.quantity = "Enter a whole number of 1 or more.";
      } else if (quantity > MAX_QUANTITY) {
        errors.quantity = "Enter 1,000,000 or fewer.";
      }
    }
    if (field === "contact_email" && !EMAIL_PATTERN.test(value)) {
      errors.contact_email = "Enter an email address like name@example.com.";
    }
    if (field === "contact_phone" && value.length < 3) {
      errors.contact_phone = "Enter at least 3 characters.";
    }
  }
  return errors;
}

const text = (value: string): string | null => value.trim() || null;

/** Body for `PATCH /api/inquiries/{id}`. An empty optional field is sent as `null`, which clears it. */
export function toUpdateBody(kind: InquiryKind, values: InquiryValues): InquiryUpdate {
  const contact = {
    name: text(values.contact_name),
    email: text(values.contact_email),
    company: text(values.contact_company),
    phone: text(values.contact_phone),
  };
  if (kind === "handoff") {
    return { contact, notes: text(values.notes) };
  }
  return {
    product: text(values.product),
    quantity: values.quantity.trim() === "" ? null : Number(values.quantity),
    timeline: text(values.timeline),
    contact,
    notes: text(values.notes),
  };
}

/** Body for `POST /api/inquiries`. The kind is set here and cannot change later. */
export function toCreateBody(
  kind: InquiryKind,
  values: InquiryValues,
  conversationId: string | null,
): InquiryCreate {
  return { kind, conversation_id: conversationId, ...toUpdateBody(kind, values) };
}

const API_FIELD_NAMES: Record<string, InquiryField> = {
  product: "product",
  quantity: "quantity",
  timeline: "timeline",
  notes: "notes",
  "contact.name": "contact_name",
  "contact.email": "contact_email",
  "contact.company": "contact_company",
  "contact.phone": "contact_phone",
  contact_name: "contact_name",
  contact_email: "contact_email",
  contact_company: "contact_company",
  contact_phone: "contact_phone",
};

/** Map API error details ("body.contact.email") to form fields; unknown locations are dropped. */
export function errorsFromDetails(details: ErrorDetail[]): InquiryErrors {
  const errors: InquiryErrors = {};
  for (const detail of details) {
    const field = API_FIELD_NAMES[(detail.field ?? "").replace(/^body\./, "")];
    if (field && !errors[field]) errors[field] = detail.message;
  }
  return errors;
}

/** Errors for the required fields the server still reports as empty. */
export function errorsFromMissingFields(kind: InquiryKind, missing: InquiryField[]): InquiryErrors {
  const errors: InquiryErrors = {};
  for (const field of missing) errors[field] = requiredMessage(kind, field);
  return errors;
}

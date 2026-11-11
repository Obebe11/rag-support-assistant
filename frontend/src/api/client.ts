/**
 * Typed API client. The types in `schema.d.ts` are generated from
 * `docs/openapi.json`; run `make openapi` after a backend contract change.
 */
import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type HealthResponse = Schemas["HealthResponse"];
export type ProviderModes = Schemas["ProviderModes"];
export type ErrorResponse = Schemas["ErrorResponse"];
export type ErrorCode = Schemas["ErrorCode"];
export type ErrorDetail = Schemas["ErrorDetail"];
export type ConversationRead = Schemas["ConversationRead"];
export type MessageRead = Schemas["MessageRead"];
export type MessageExchange = Schemas["MessageExchange"];
export type Citation = Schemas["Citation"];
export type InquiryRead = Schemas["InquiryRead"];
export type InquiryCreate = Schemas["InquiryCreate"];
export type InquiryUpdate = Schemas["InquiryUpdate"];
export type InquiryKind = Schemas["InquiryKind"];
export type InquiryField = Schemas["InquiryField"];
export type InquiryList = Schemas["InquiryList"];
export type DeliveryRead = Schemas["DeliveryRead"];
export type DeliveryStatus = Schemas["DeliveryStatus"];
export type DocumentRead = Schemas["DocumentRead"];
export type DocumentDetail = Schemas["DocumentDetail"];
export type DocumentVersionRead = Schemas["DocumentVersionRead"];
export type DocumentList = Schemas["DocumentList"];
export type IndexingStatus = Schemas["IndexingStatus"];

const baseUrl: string = import.meta.env.VITE_API_BASE_URL ?? window.location.origin;

// Look up `fetch` on every call, so tests can replace it.
const deferredFetch: typeof fetch = (input, init) => globalThis.fetch(input, init);

/** Client for visitor endpoints. */
export const api = createClient<paths>({ baseUrl, fetch: deferredFetch });

/** Client for `/api/admin` endpoints. The token is the server's ADMIN_API_TOKEN. */
export function createAdminApi(token: string) {
  return createClient<paths>({
    baseUrl,
    fetch: deferredFetch,
    headers: { Authorization: `Bearer ${token}` },
  });
}

export type AdminApi = ReturnType<typeof createAdminApi>;

/**
 * Body serializer for the multipart upload endpoints: sends the file and the
 * optional text fields as `multipart/form-data`. Empty values are left out.
 */
export function toFormData(body: unknown): FormData {
  const form = new FormData();
  for (const [key, value] of Object.entries((body ?? {}) as Record<string, unknown>)) {
    if (value instanceof Blob) {
      form.append(key, value, value instanceof File ? value.name : undefined);
    } else if (typeof value === "string" && value !== "") {
      form.append(key, value);
    }
  }
  return form;
}

/** An API error in the common format, or a transport failure (`status` 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode | "network_error";
  readonly details: Schemas["ErrorDetail"][];

  constructor(
    status: number,
    code: ErrorCode | "network_error",
    message: string,
    details: Schemas["ErrorDetail"][] = [],
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/**
 * Unwrap an openapi-fetch result: return the data or throw an `ApiError`.
 *
 * @example
 * const health = await unwrap(api.GET("/api/health"));
 */
export async function unwrap<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response };
  try {
    result = await request;
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the server.");
  }
  if (result.response.ok) {
    return result.data as T;
  }
  const body = result.error as Partial<ErrorResponse> | undefined;
  if (body?.error) {
    throw new ApiError(
      result.response.status,
      body.error.code,
      body.error.message,
      body.error.details,
    );
  }
  throw new ApiError(result.response.status, "internal_error", "The server returned an error.");
}

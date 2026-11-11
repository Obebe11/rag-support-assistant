import { ApiError } from "../api/client";

/** What the visitor or administrator reads when a request fails. */
export interface UiError {
  kind: "network" | "server" | "request" | "auth";
  title: string;
  /** What happened and what to do next. */
  message: string;
  status: number;
}

/**
 * Turn a thrown value into text for the UI.
 *
 * Transport failures and 5xx responses get fixed wording; a 4xx response in the
 * common API format shows the server's own message, because it explains what
 * to change.
 */
export function describeError(error: unknown): UiError {
  if (error instanceof ApiError) {
    if (error.status === 0) {
      return {
        kind: "network",
        title: "Cannot reach the server",
        message: "Check your connection and try again.",
        status: 0,
      };
    }
    if (error.status === 401 || error.status === 403) {
      return {
        kind: "auth",
        title: "Access denied",
        message: error.message,
        status: error.status,
      };
    }
    if (error.status >= 500) {
      return {
        kind: "server",
        title: "The server could not complete the request",
        message:
          error.status === 501
            ? "This feature is not available on the server yet."
            : "This is a problem on our side. Try again in a moment.",
        status: error.status,
      };
    }
    return {
      kind: "request",
      title: "The request was not accepted",
      message: error.message,
      status: error.status,
    };
  }
  return {
    kind: "server",
    title: "Something went wrong",
    message: "Try again in a moment.",
    status: -1,
  };
}

import { useCallback, useMemo, useState } from "react";

import { ApiError, createAdminApi, unwrap } from "../../api/client";
import type { AdminApi } from "../../api/client";
import { describeError } from "../../lib/errors";
import type { UiError } from "../../lib/errors";

export interface AdminSession {
  /** `null` until a token is accepted. */
  client: AdminApi | null;
  checking: boolean;
  error: UiError | null;
  signIn: (token: string) => Promise<void>;
  /** Forget the token. `reason` is shown on the token form. */
  signOut: (reason?: UiError) => void;
  /** Call from a failed admin request: an auth error ends the session. Returns true if it did. */
  handleAuthError: (error: unknown) => boolean;
}

/** What 401 and 403 mean for the administrator, per the API contract. */
export function describeAuthError(error: unknown): UiError {
  if (error instanceof ApiError && error.status === 401) {
    return {
      kind: "auth",
      title: "A token is required",
      message: "The server did not receive an admin token. Enter the token and try again.",
      status: 401,
    };
  }
  if (error instanceof ApiError && error.status === 403) {
    return {
      kind: "auth",
      title: "Token not accepted",
      message:
        "The server rejected this token. Check that it matches ADMIN_API_TOKEN on the server. If no token is configured there, admin access is turned off.",
      status: 403,
    };
  }
  return describeError(error);
}

function isAuthError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

/**
 * Holds the admin token in memory for this page view only. It is never written
 * to localStorage, sessionStorage or the address, so a reload asks for it again.
 */
export function useAdminSession(): AdminSession {
  const [token, setToken] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<UiError | null>(null);

  const client = useMemo(() => (token === null ? null : createAdminApi(token)), [token]);

  const signIn = useCallback(async (candidate: string) => {
    const trimmed = candidate.trim();
    if (trimmed === "") {
      setError({ kind: "auth", title: "A token is required", message: "Enter the admin token.", status: 0 });
      return;
    }
    setChecking(true);
    setError(null);
    try {
      // Any admin endpoint proves the token; the document list is the first screen anyway.
      await unwrap(createAdminApi(trimmed).GET("/api/admin/documents", { params: { query: { limit: 1 } } }));
      setToken(trimmed);
    } catch (caught) {
      setError(describeAuthError(caught));
    } finally {
      setChecking(false);
    }
  }, []);

  const signOut = useCallback((reason?: UiError) => {
    setToken(null);
    setError(reason ?? null);
  }, []);

  const handleAuthError = useCallback(
    (caught: unknown) => {
      if (!isAuthError(caught)) return false;
      signOut(describeAuthError(caught));
      return true;
    },
    [signOut],
  );

  return { client, checking, error, signIn, signOut, handleAuthError };
}

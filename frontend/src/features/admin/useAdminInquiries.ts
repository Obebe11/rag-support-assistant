import { useCallback, useEffect, useRef, useState } from "react";

import { unwrap } from "../../api/client";
import type { AdminApi, InquiryRead } from "../../api/client";
import { describeError } from "../../lib/errors";
import type { UiError } from "../../lib/errors";

export interface AdminInquiries {
  status: "loading" | "ready" | "error";
  items: InquiryRead[];
  total: number;
  loadError: UiError | null;
  reload: () => void;
}

const PAGE_SIZE = 100;

/** Inquiries with their delivery status, newest first as the server returns them. */
export function useAdminInquiries(client: AdminApi, onAuthError: (error: unknown) => boolean): AdminInquiries {
  const [status, setStatus] = useState<AdminInquiries["status"]>("loading");
  const [items, setItems] = useState<InquiryRead[]>([]);
  const [total, setTotal] = useState(0);
  const [loadError, setLoadError] = useState<UiError | null>(null);
  const [version, setVersion] = useState(0);
  const authRef = useRef(onAuthError);
  useEffect(() => {
    authRef.current = onAuthError;
  }, [onAuthError]);

  useEffect(() => {
    let active = true;
    unwrap(client.GET("/api/admin/inquiries", { params: { query: { limit: PAGE_SIZE } } })).then(
      (list) => {
        if (!active) return;
        setItems(list.items);
        setTotal(list.total);
        setStatus("ready");
        setLoadError(null);
      },
      (error: unknown) => {
        if (!active || authRef.current(error)) return;
        setStatus("error");
        setLoadError(describeError(error));
      },
    );
    return () => {
      active = false;
    };
  }, [client, version]);

  const reload = useCallback(() => {
    setStatus("loading");
    setVersion((current) => current + 1);
  }, []);

  return { status, items, total, loadError, reload };
}

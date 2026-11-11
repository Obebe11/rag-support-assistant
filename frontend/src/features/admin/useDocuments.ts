import { useCallback, useEffect, useRef, useState } from "react";

import { toFormData, unwrap } from "../../api/client";
import type { AdminApi, DocumentDetail, DocumentList, DocumentRead } from "../../api/client";
import { describeError } from "../../lib/errors";
import type { UiError } from "../../lib/errors";
import { timing } from "../../lib/timing";

export interface UploadInput {
  file: File;
  title?: string;
  versionLabel?: string;
}

export interface Documents {
  status: "loading" | "ready" | "error";
  items: DocumentRead[];
  total: number;
  loadError: UiError | null;
  reload: () => void;
  /** Each action resolves to `null` on success or to the error to show. */
  upload: (input: UploadInput) => Promise<UiError | null>;
  replace: (documentId: string, input: UploadInput) => Promise<UiError | null>;
  remove: (documentId: string) => Promise<UiError | null>;
  loadVersions: (documentId: string) => Promise<DocumentDetail | UiError>;
}

const PAGE_SIZE = 100;

export const ACCEPTED_EXTENSIONS = [".md", ".markdown", ".pdf"];

export function isAcceptedFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((extension) => name.endsWith(extension));
}

function isIndexing(document: DocumentRead): boolean {
  const status = document.latest_version.indexing_status;
  return status === "pending" || status === "indexing";
}

/**
 * Document list with upload, replace and delete. While any document is being
 * indexed the list refreshes on a timer, so the status moves without a reload.
 */
export function useDocuments(
  client: AdminApi,
  onAuthError: (error: unknown) => boolean,
  pollIntervalMs: number = timing.documentsPollMs,
): Documents {
  const [status, setStatus] = useState<Documents["status"]>("loading");
  const [items, setItems] = useState<DocumentRead[]>([]);
  const [total, setTotal] = useState(0);
  const [loadError, setLoadError] = useState<UiError | null>(null);
  const [version, setVersion] = useState(0);
  const authRef = useRef(onAuthError);
  useEffect(() => {
    authRef.current = onAuthError;
  }, [onAuthError]);

  const requestList = useCallback(
    () => unwrap(client.GET("/api/admin/documents", { params: { query: { limit: PAGE_SIZE } } })),
    [client],
  );

  const applyList = useCallback((list: DocumentList) => {
    setItems(list.items);
    setTotal(list.total);
    setStatus("ready");
    setLoadError(null);
  }, []);

  const fetchList = useCallback(async () => {
    applyList(await requestList());
  }, [applyList, requestList]);

  useEffect(() => {
    let active = true;
    requestList().then(
      (list) => {
        if (active) applyList(list);
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
  }, [applyList, requestList, version]);

  const indexing = status === "ready" && items.some(isIndexing);
  useEffect(() => {
    if (!indexing) return;
    const timer = setInterval(() => {
      // A failed refresh keeps the last list; the next tick tries again.
      fetchList().catch((error: unknown) => void authRef.current(error));
    }, pollIntervalMs);
    return () => clearInterval(timer);
  }, [fetchList, indexing, pollIntervalMs]);

  const reload = useCallback(() => {
    setStatus("loading");
    setVersion((current) => current + 1);
  }, []);

  const run = useCallback(
    async (action: () => Promise<unknown>): Promise<UiError | null> => {
      try {
        await action();
        await fetchList();
        return null;
      } catch (error) {
        if (authRef.current(error)) return null;
        return describeError(error);
      }
    },
    [fetchList],
  );

  const upload = useCallback(
    (input: UploadInput) =>
      run(() =>
        unwrap(
          client.POST("/api/admin/documents", {
            // The generated type describes the file as a string; the form sends the File itself.
            body: {
              file: input.file as unknown as string,
              title: input.title,
              version_label: input.versionLabel,
            },
            bodySerializer: toFormData,
          }),
        ),
      ),
    [client, run],
  );

  const replace = useCallback(
    (documentId: string, input: UploadInput) =>
      run(() =>
        unwrap(
          client.POST("/api/admin/documents/{document_id}/versions", {
            params: { path: { document_id: documentId } },
            body: { file: input.file as unknown as string, version_label: input.versionLabel },
            bodySerializer: toFormData,
          }),
        ),
      ),
    [client, run],
  );

  const remove = useCallback(
    (documentId: string) =>
      run(() =>
        unwrap(
          client.DELETE("/api/admin/documents/{document_id}", {
            params: { path: { document_id: documentId } },
          }),
        ),
      ),
    [client, run],
  );

  const loadVersions = useCallback(
    async (documentId: string): Promise<DocumentDetail | UiError> => {
      try {
        return await unwrap(
          client.GET("/api/admin/documents/{document_id}", { params: { path: { document_id: documentId } } }),
        );
      } catch (error) {
        authRef.current(error);
        return describeError(error);
      }
    },
    [client],
  );

  return { status, items, total, loadError, reload, upload, replace, remove, loadVersions };
}

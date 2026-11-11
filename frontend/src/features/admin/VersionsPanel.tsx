import { CircleAlertIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "~/components/ui/alert";
import { Badge } from "~/components/ui/badge";
import { Skeleton } from "~/components/ui/skeleton";

import type { DocumentDetail, DocumentRead } from "../../api/client";
import type { UiError } from "../../lib/errors";
import { formatBytes, formatDateTime, INDEXING_VIEW, versionName } from "./format";
import type { Documents } from "./useDocuments";

type VersionsState =
  | { status: "loading" }
  | { status: "error"; error: UiError }
  | { status: "ready"; detail: DocumentDetail };

/** Version history of one document, newest first as the server returns it. */
export function VersionsPanel(props: { document: DocumentRead; loadVersions: Documents["loadVersions"] }) {
  const { document, loadVersions } = props;
  const [state, setState] = useState<VersionsState>({ status: "loading" });
  const latest = document.latest_version;

  // Reload when the list shows a new upload or a new indexing status for this document.
  useEffect(() => {
    let active = true;
    loadVersions(document.id).then((result) => {
      if (!active) return;
      setState("versions" in result ? { status: "ready", detail: result } : { status: "error", error: result });
    });
    return () => {
      active = false;
    };
  }, [document.id, latest.id, latest.indexing_status, loadVersions]);

  return (
    <section className="px-4 pb-6 pt-1 sm:px-5" aria-label={`Versions of ${document.title}`}>
      <h2 className="m-0 text-sm font-medium text-foreground [overflow-wrap:anywhere]">{document.title}</h2>
      <p className="m-0 mt-1 text-xs leading-relaxed text-muted-foreground">
        The assistant cites the active version only.
      </p>

      {state.status === "loading" ? (
        <div className="mt-4 flex flex-col gap-3" aria-busy="true" aria-label="Loading versions">
          <Skeleton className="h-20 w-full rounded-xl" />
          <Skeleton className="h-20 w-full rounded-xl" />
        </div>
      ) : null}

      {state.status === "error" ? (
        <Alert variant="error" controlAlignment="first-line" className="mt-4">
          <CircleAlertIcon aria-hidden />
          <AlertTitle>{state.error.title}</AlertTitle>
          <AlertDescription>{state.error.message}</AlertDescription>
        </Alert>
      ) : null}

      {state.status === "ready" ? (
        <ol className="m-0 mt-4 flex list-none flex-col gap-3 p-0">
          {state.detail.versions.map((version) => {
            const indexing = INDEXING_VIEW[version.indexing_status];
            const facts = [
              formatBytes(version.byte_size),
              version.page_count != null ? `${version.page_count} pages` : null,
              version.chunk_count != null ? `${version.chunk_count} passages` : null,
            ].filter(Boolean);
            return (
              <li key={version.id} className="rounded-xl border border-border/60 bg-card/50 p-3">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <h3 className="m-0 text-sm font-medium text-foreground">{versionName(version)}</h3>
                  {version.is_active ? <Badge variant="outline">Active</Badge> : null}
                  <Badge variant={indexing.variant}>{indexing.label}</Badge>
                </div>
                <p className="m-0 mt-1 text-xs text-muted-foreground [overflow-wrap:anywhere]">
                  {version.source_filename}
                </p>
                <p className="m-0 mt-0.5 text-xs text-muted-foreground tabular-nums">{facts.join(", ")}</p>
                <p className="m-0 mt-0.5 text-xs text-muted-foreground">
                  Uploaded {formatDateTime(version.created_at)}
                </p>
                {version.indexing_error ? (
                  <p className="m-0 mt-1.5 text-xs text-destructive-foreground [overflow-wrap:anywhere]">
                    {version.indexing_error}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ol>
      ) : null}
    </section>
  );
}

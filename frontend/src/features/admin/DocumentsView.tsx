import { CircleAlertIcon } from "lucide-react";

import { Alert, AlertAction, AlertDescription, AlertTitle } from "~/components/ui/alert";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "~/components/ui/empty";
import { Skeleton } from "~/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "~/components/ui/table";

import type { DocumentRead } from "../../api/client";
import { formatDateTime, INDEXING_VIEW, versionName } from "./format";
import type { Documents } from "./useDocuments";

export interface DocumentActions {
  onUpload: () => void;
  onVersions: (document: DocumentRead) => void;
  onReplace: (document: DocumentRead) => void;
  onDelete: (document: DocumentRead) => void;
}

function ActiveVersion({ document }: { document: DocumentRead }) {
  if (!document.active_version) {
    return <span className="text-muted-foreground">None, not cited yet</span>;
  }
  return <span>{versionName(document.active_version)}</span>;
}

/** Indexing status of the newest upload; it differs from the active version while a replacement is indexed. */
function LatestUpload({ document }: { document: DocumentRead }) {
  const latest = document.latest_version;
  const view = INDEXING_VIEW[latest.indexing_status];
  const isReplacement = document.active_version != null && document.active_version.id !== latest.id;
  return (
    <div className="flex min-w-0 flex-col items-start gap-1">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Badge variant={view.variant}>{view.label}</Badge>
        {isReplacement ? <span className="text-xs text-muted-foreground">{versionName(latest)}</span> : null}
      </div>
      {latest.indexing_error ? (
        <p className="m-0 max-w-64 text-xs whitespace-normal text-destructive-foreground [overflow-wrap:anywhere]">
          {latest.indexing_error}
        </p>
      ) : null}
    </div>
  );
}

function RowActions({ document, actions }: { document: DocumentRead; actions: DocumentActions }) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      <Button variant="ghost" size="xs" onClick={() => actions.onVersions(document)}>
        Versions<span className="sr-only"> of {document.title}</span>
      </Button>
      <Button variant="ghost" size="xs" onClick={() => actions.onReplace(document)}>
        Replace<span className="sr-only"> {document.title}</span>
      </Button>
      <Button
        variant="ghost"
        size="xs"
        className="text-destructive-foreground"
        onClick={() => actions.onDelete(document)}
      >
        Delete<span className="sr-only"> {document.title}</span>
      </Button>
    </div>
  );
}

export function DocumentsView(props: { documents: Documents; actions: DocumentActions; compact: boolean }) {
  const { documents, actions } = props;

  if (documents.status === "loading") {
    return (
      <div className="flex flex-col gap-2 pt-2" aria-busy="true" aria-label="Loading documents">
        {[0, 1, 2, 3].map((row) => (
          <Skeleton key={row} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (documents.status === "error" && documents.loadError) {
    return (
      <Alert variant="error" className="mt-2">
        <CircleAlertIcon aria-hidden />
        <AlertTitle>{documents.loadError.title}</AlertTitle>
        <AlertDescription>{documents.loadError.message}</AlertDescription>
        <AlertAction>
          <Button variant="outline" size="xs" onClick={documents.reload}>
            Try again
          </Button>
        </AlertAction>
      </Alert>
    );
  }

  if (documents.items.length === 0) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle className="text-base font-medium">No documents yet</EmptyTitle>
          <EmptyDescription>
            Upload a Markdown or PDF file. The assistant answers only from indexed documents.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button onClick={actions.onUpload}>Upload document</Button>
        </EmptyContent>
      </Empty>
    );
  }

  if (props.compact) {
    return (
      <ul className="m-0 flex list-none flex-col gap-3 p-0 pt-2">
        {documents.items.map((document) => (
          <li key={document.id} className="rounded-xl border border-border/60 bg-card/50 p-3">
            <h3 className="m-0 text-sm font-medium text-foreground [overflow-wrap:anywhere]">{document.title}</h3>
            <p className="m-0 mt-0.5 text-xs text-muted-foreground [overflow-wrap:anywhere]">
              {document.latest_version.source_filename}
            </p>
            <dl className="m-0 mt-2.5 flex flex-col gap-1.5 text-sm">
              <div className="flex gap-3">
                <dt className="w-28 shrink-0 text-muted-foreground">Active version</dt>
                <dd className="m-0 min-w-0 flex-1">
                  <ActiveVersion document={document} />
                </dd>
              </div>
              <div className="flex gap-3">
                <dt className="w-28 shrink-0 text-muted-foreground">Latest upload</dt>
                <dd className="m-0 min-w-0 flex-1">
                  <LatestUpload document={document} />
                </dd>
              </div>
              <div className="flex gap-3">
                <dt className="w-28 shrink-0 text-muted-foreground">Updated</dt>
                <dd className="m-0 min-w-0 flex-1">{formatDateTime(document.updated_at)}</dd>
              </div>
            </dl>
            <div className="mt-2.5 -ml-1.5">
              <RowActions document={document} actions={actions} />
            </div>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <Table className="text-sm">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="text-muted-foreground">Document</TableHead>
          <TableHead className="text-muted-foreground">Active version</TableHead>
          <TableHead className="text-muted-foreground">Latest upload</TableHead>
          <TableHead className="text-muted-foreground">Updated</TableHead>
          <TableHead className="text-muted-foreground">
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {documents.items.map((document) => (
          <TableRow key={document.id}>
            <TableCell className="max-w-72 whitespace-normal">
              <div className="font-medium text-foreground [overflow-wrap:anywhere]">{document.title}</div>
              <div className="text-xs text-muted-foreground [overflow-wrap:anywhere]">
                {document.latest_version.source_filename}
              </div>
            </TableCell>
            <TableCell>
              <ActiveVersion document={document} />
            </TableCell>
            <TableCell className="whitespace-normal">
              <LatestUpload document={document} />
            </TableCell>
            <TableCell className="text-muted-foreground tabular-nums">
              {formatDateTime(document.updated_at)}
            </TableCell>
            <TableCell>
              <div className="flex justify-end">
                <RowActions document={document} actions={actions} />
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

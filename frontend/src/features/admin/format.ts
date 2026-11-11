import type { DocumentVersionRead, IndexingStatus } from "../../api/client";

const DATE_TIME = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" });

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : DATE_TIME.format(date);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function versionName(version: DocumentVersionRead): string {
  return `Version ${version.version_label ?? version.version_number}`;
}

export type StatusVariant = "info" | "success" | "error" | "warning" | "outline";

export const INDEXING_VIEW: Record<IndexingStatus, { label: string; variant: StatusVariant }> = {
  pending: { label: "Queued", variant: "info" },
  indexing: { label: "Indexing", variant: "info" },
  ready: { label: "Indexed", variant: "success" },
  failed: { label: "Indexing failed", variant: "error" },
};

import type { Citation } from "../../api/client";

/**
 * "Version 3.0, page 2" or "Version 4, Returns › Return window": where the
 * excerpt comes from. The API gives `section` as a heading path joined with
 * " > "; a page number exists for PDF sources only; an introduction has neither.
 */
export function sourceLocation(citation: Citation): string {
  const parts = [`Version ${citation.version_label ?? citation.version_number}`];
  if (citation.page_number != null) parts.push(`page ${citation.page_number}`);
  if (citation.section) parts.push(citation.section.split(" > ").join(" › "));
  return parts.join(", ");
}

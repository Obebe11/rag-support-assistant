import type { Citation } from "../../api/client";

/** "Version 3.0, page 2" or "Version 4, Return window": where the excerpt comes from. */
export function sourceLocation(citation: Citation): string {
  const parts = [`Version ${citation.version_label ?? citation.version_number}`];
  if (citation.page_number != null) parts.push(`page ${citation.page_number}`);
  if (citation.section) parts.push(citation.section);
  return parts.join(", ");
}

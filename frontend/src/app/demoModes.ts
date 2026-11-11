import type { HealthResponse, ProviderModes } from "../api/client";

/**
 * One line per provider that is not live. Local and simulated modes must always
 * be labeled: they are not a working LLM or a live CRM integration.
 */
export function describeDemoModes(providers: ProviderModes): string[] {
  const notes: string[] = [];
  if (!providers.llm.live) {
    notes.push("Local answer mode: no LLM is connected.");
  }
  if (!providers.embeddings.live) {
    notes.push("Local search mode: no embedding API is connected.");
  }
  if (!providers.crm.live) {
    notes.push("Simulated CRM: inquiries are not sent to a real CRM.");
  }
  return notes;
}

/** True when the CRM access check failed; the server then reports `status: degraded`. */
export function crmAccessFailed(health: HealthResponse): boolean {
  return health.providers.crm.access?.state === "failed";
}

export interface ModeRow {
  name: string;
  value: string;
  tone: "live" | "demo" | "error";
}

/** The three providers as short rows for the sidebar. */
export function modeRows(health: HealthResponse): ModeRow[] {
  const { llm, embeddings, crm } = health.providers;
  const tone = (live: boolean): ModeRow["tone"] => (live ? "live" : "demo");
  return [
    { name: "Answers", value: llm.live ? "Live model" : "Local mode", tone: tone(llm.live) },
    { name: "Search", value: embeddings.live ? "Embedding API" : "Local mode", tone: tone(embeddings.live) },
    crmAccessFailed(health)
      ? { name: "CRM", value: "Access failed", tone: "error" }
      : { name: "CRM", value: crm.live ? "Connected" : "Simulated", tone: tone(crm.live) },
  ];
}

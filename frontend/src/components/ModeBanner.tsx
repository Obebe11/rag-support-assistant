import type { ProviderModes } from "../api/client";
import { useHealth } from "../hooks/useHealth";
import "./ModeBanner.css";

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

export function ModeBanner() {
  const { state, reload } = useHealth();

  if (state.status === "loading") {
    return null;
  }

  if (state.status === "error") {
    return (
      <div className="mode-banner mode-banner--error" role="alert">
        <div className="mode-banner__inner">
          <p className="mode-banner__title">Cannot reach the server</p>
          <p className="mode-banner__text">The assistant is unavailable right now.</p>
          <button type="button" className="mode-banner__action" onClick={reload}>
            Try again
          </button>
        </div>
      </div>
    );
  }

  const { health } = state;
  const notes = describeDemoModes(health.providers);
  const databaseDown = health.database !== "ok";

  if (!databaseDown && notes.length === 0) {
    return null;
  }

  return (
    <>
      {databaseDown && (
        <div className="mode-banner mode-banner--error" role="alert">
          <div className="mode-banner__inner">
            <p className="mode-banner__title">Database unavailable</p>
            <p className="mode-banner__text">The assistant cannot answer right now.</p>
            <button type="button" className="mode-banner__action" onClick={reload}>
              Try again
            </button>
          </div>
        </div>
      )}
      {notes.length > 0 && (
        <aside className="mode-banner" aria-label="Demo mode">
          <div className="mode-banner__inner">
            <p className="mode-banner__title">Demo mode</p>
            <ul className="mode-banner__list">
              {notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </div>
        </aside>
      )}
    </>
  );
}

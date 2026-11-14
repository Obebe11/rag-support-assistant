import { ChevronRightIcon } from "lucide-react";

import type { Citation } from "../../api/client";
import { sourceLocation } from "./sources";

/**
 * The sources of an answer, under the answer text. Each row opens the
 * full excerpt in the side panel. The retrieval `score` is not shown: it ranks
 * passages and says nothing about whether the answer is correct.
 */
export function SourcesList(props: {
  citations: Citation[];
  /** The side panel shows these sources in full right now, so the rows stay short. */
  shownInPanel: boolean;
  onOpen: (index: number) => void;
}) {
  return (
    <section className="mt-3" aria-label="Sources">
      <div className="mb-1.5 flex items-baseline gap-2 px-0.5 text-xs text-muted-foreground">
        <h3 className="m-0 text-xs font-medium">Sources</h3>
        {props.shownInPanel ? <span>Shown in the side panel</span> : null}
      </div>
      <ol className="m-0 flex list-none flex-col gap-1.5 p-0">
        {props.citations.map((citation, index) => (
          <li key={citation.chunk_id}>
            <button
              type="button"
              onClick={() => props.onOpen(index)}
              className="flex w-full cursor-pointer items-start gap-2.5 rounded-md border border-border/60 bg-card/50 px-2.5 py-2 text-left text-[13px] outline-none transition hover:bg-accent/50 focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span aria-hidden className="w-3 shrink-0 text-right tabular-nums text-muted-foreground">
                {index + 1}
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="truncate font-medium text-foreground">{citation.document_title}</span>
                <span className="truncate text-xs text-muted-foreground">{sourceLocation(citation)}</span>
                {props.shownInPanel ? null : (
                  <span className="line-clamp-2 text-xs leading-relaxed text-foreground/70 [overflow-wrap:anywhere]">
                    {citation.excerpt}
                  </span>
                )}
              </span>
              <ChevronRightIcon aria-hidden className="mt-0.5 size-3.5 shrink-0 text-icon-muted" />
              <span className="sr-only">Open the full excerpt</span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

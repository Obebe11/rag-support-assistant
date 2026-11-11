import { useEffect, useRef } from "react";

import { cn } from "~/lib/utils";

import type { Citation } from "../../api/client";
import { sourceLocation } from "./sources";

/** Full excerpts for one grounded answer, in the side panel. */
export function SourcesPanel(props: { citations: Citation[]; highlightedIndex: number | null }) {
  const listRef = useRef<HTMLOListElement | null>(null);

  useEffect(() => {
    if (props.highlightedIndex === null) return;
    const item = listRef.current?.children[props.highlightedIndex];
    if (item instanceof HTMLElement && typeof item.scrollIntoView === "function") {
      item.scrollIntoView({ block: "nearest" });
    }
  }, [props.highlightedIndex, props.citations]);

  if (props.citations.length === 0) {
    return (
      <p className="m-0 flex flex-1 items-center justify-center px-5 text-center text-xs text-muted-foreground">
        Sources appear here when an answer cites the Northline documents.
      </p>
    );
  }

  return (
    <div className="px-4 pb-6 pt-1 sm:px-5">
      <h2 className="m-0 text-sm font-medium text-foreground">Sources for this answer</h2>
      <p className="m-0 mt-1 text-xs leading-relaxed text-muted-foreground">
        Passages from the Northline documents that the answer cites.
      </p>
      <ol ref={listRef} className="m-0 mt-4 flex list-none flex-col gap-3 p-0">
        {props.citations.map((citation, index) => (
          <li
            key={citation.chunk_id}
            className={cn(
              "rounded-xl border bg-card/50 p-3",
              index === props.highlightedIndex ? "border-ring/60 ring-2 ring-ring/20" : "border-border/60",
            )}
            aria-current={index === props.highlightedIndex ? "true" : undefined}
          >
            <div className="flex items-baseline gap-2">
              <span aria-hidden className="shrink-0 text-xs tabular-nums text-muted-foreground">
                {index + 1}
              </span>
              <h3 className="m-0 min-w-0 text-sm font-medium text-foreground [overflow-wrap:anywhere]">
                {citation.document_title}
              </h3>
            </div>
            <p className="m-0 mt-0.5 text-xs text-muted-foreground [overflow-wrap:anywhere]">
              {sourceLocation(citation)}
            </p>
            <blockquote className="m-0 mt-2.5 border-l-2 border-border pl-3 text-sm leading-relaxed whitespace-pre-wrap text-foreground/80 [overflow-wrap:anywhere]">
              {citation.excerpt}
            </blockquote>
          </li>
        ))}
      </ol>
    </div>
  );
}

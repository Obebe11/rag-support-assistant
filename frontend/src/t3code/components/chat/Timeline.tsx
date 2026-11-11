/*
 * Adapted from T3 Code (apps/web/src/components/chat/MessagesTimeline.tsx and
 * DraftHeroHeadline.tsx, MIT, (c) 2026 T3 Tools Inc.). Handoff AI keeps the
 * markup and classes of the scroll viewport, the centered column, the user
 * bubble, the assistant block and the working row. The virtualized list, tool
 * and plan rows, attachments, revert and copy actions are not ported; the
 * viewport is a plain scroll container.
 */
import type { ComponentPropsWithoutRef, ReactNode, Ref } from "react";

import { cn } from "~/lib/utils";

export function TimelineViewport({
  children,
  bottomInset,
  scrollRef,
  label,
}: {
  children: ReactNode;
  /** Height reserved under the last row for the docked composer, in px. */
  bottomInset: number;
  scrollRef?: Ref<HTMLDivElement>;
  label: string;
}) {
  return (
    <div className="relative h-full min-h-0">
      <div
        ref={scrollRef}
        role="log"
        aria-label={label}
        aria-live="polite"
        aria-relevant="additions"
        tabIndex={0}
        className="topbar-scroll-fade h-full min-h-0 overflow-x-hidden overflow-y-auto overscroll-y-contain px-3 outline-none [overflow-anchor:none] [scrollbar-gutter:stable_both-edges] sm:px-5"
      >
        {/* Taller than upstream (h-10 sm:h-12): a one-row status banner fits here. */}
        <div className="h-14" />
        {children}
        <div className="h-3 sm:h-4" />
        <div aria-hidden style={{ height: bottomInset }} />
      </div>
    </div>
  );
}

export type TimelineRowSpacing = "tight" | "default";

export function TimelineRow({
  spacing = "default",
  className,
  children,
  ...rest
}: ComponentPropsWithoutRef<"div"> & {
  spacing?: TimelineRowSpacing;
  "data-message-role"?: "user" | "assistant";
}) {
  return (
    <div className="mx-auto w-full min-w-0 max-w-3xl overflow-x-clip" data-timeline-root="true">
      <div
        className={cn(
          spacing === "tight" ? "pb-2" : "pb-4",
          rest["data-message-role"] === "assistant" ? "group/assistant" : null,
          className,
        )}
        {...rest}
      >
        {children}
      </div>
    </div>
  );
}

export function UserMessage(props: { children: ReactNode; footer?: ReactNode; dimmed?: boolean }) {
  return (
    <div className="group flex flex-col items-end gap-1">
      <div
        className={cn(
          "relative max-w-[80%] rounded-2xl bg-message p-3 text-message-foreground",
          props.dimmed && "opacity-70",
        )}
      >
        <div className="whitespace-pre-wrap wrap-break-word text-message-foreground text-sm leading-relaxed">
          {props.children}
        </div>
      </div>
      {props.footer ? (
        <div className="flex w-full max-w-[80%] items-center justify-end pe-1 text-xs">
          {props.footer}
        </div>
      ) : null}
    </div>
  );
}

export function AssistantMessage(props: { children: ReactNode }) {
  return <div className="relative min-w-0 px-1 py-0.5">{props.children}</div>;
}

/** The "Working..." row with the sweeping highlight used while a reply is pending. */
export function WorkingRow(props: { label: string; activity: string }) {
  return (
    <div>
      <div className="border-b border-border/60 pb-2 pt-1">
        <div className="px-1 text-sm leading-relaxed text-muted-foreground tabular-nums">
          {props.label}
        </div>
      </div>
      <div className="mt-1">
        <div className="relative min-h-6 w-fit max-w-full min-w-0 overflow-hidden rounded-md text-sm leading-relaxed">
          <LiveActivityContent label={props.activity} />
          <div
            aria-hidden
            className="live-activity-focus pointer-events-none absolute inset-y-0 select-none"
          >
            <div className="live-activity-focus-counter">
              <div className="live-activity-focus-aligned">
                <LiveActivityContent label={props.activity} highlighted />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function LiveActivityContent(props: { label: string; highlighted?: boolean }) {
  return (
    <div
      className={cn(
        "flex min-h-6 min-w-0 items-center gap-1.5 px-1 py-0.5",
        props.highlighted ? "text-foreground" : "text-secondary-label",
      )}
    >
      <span className="min-w-0 flex-1 truncate">{props.label}</span>
    </div>
  );
}

export function DraftHeroHeadline(props: { children: ReactNode; id?: string }) {
  return (
    <h2
      id={props.id}
      className="mx-auto w-full max-w-5xl text-center font-normal text-2xl text-foreground tracking-tight sm:text-3xl"
    >
      {props.children}
    </h2>
  );
}

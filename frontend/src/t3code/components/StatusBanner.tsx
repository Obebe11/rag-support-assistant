/*
 * Adapted from T3 Code (apps/web/src/components/chat/ProviderStatusBanner.tsx,
 * MIT, (c) 2026 T3 Tools Inc.). Handoff AI keeps the floating glass alert that
 * overlays the top of the content, and replaces the dismiss button with an
 * optional action. The alert is one row, so it fits in the timeline's top
 * spacer and never covers a message; `placement="inline"` puts it in the page
 * flow for pages without that spacer.
 */
import { InfoIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "~/lib/utils";

export function StatusBanner(props: {
  variant: "warning" | "error";
  title: string;
  /** Shown next to the title on wide windows; read by screen readers everywhere. */
  message?: string;
  action?: ReactNode;
  placement?: "overlay" | "inline";
}) {
  const inline = props.placement === "inline";
  return (
    <div className={inline ? "shrink-0 px-3 pb-2 sm:px-5" : "pointer-events-none absolute inset-x-0 top-0 z-20"}>
      <div className={cn("pointer-events-auto w-fit max-w-full", inline ? "" : "mx-auto max-w-[calc(100%-1.5rem)] pt-2")}>
        <div
          className={cn(
            "alert-glass relative flex min-h-9 items-center gap-2.5 rounded-xl border py-1 ps-3 pe-1.5 text-card-foreground text-sm",
            props.variant === "warning"
              ? "border-warning/32 [&_svg]:text-warning"
              : "border-destructive/32 [&_svg]:text-destructive",
          )}
          data-variant={props.variant}
          role="alert"
        >
          <InfoIcon className="size-4 shrink-0" aria-hidden />
          <p className="m-0 min-w-0 flex-1 py-1 leading-snug">
            <span className="font-medium">{props.title}</span>
            {props.message ? (
              <span className="text-muted-foreground max-sm:sr-only"> {props.message}</span>
            ) : null}
          </p>
          {props.action}
        </div>
      </div>
    </div>
  );
}

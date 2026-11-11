import { Button } from "~/components/ui/button";
import { Popover, PopoverDescription, PopoverPopup, PopoverTitle, PopoverTrigger } from "~/components/ui/popover";
import { cn } from "~/lib/utils";

import { useHealth } from "../hooks/useHealth";
import { crmAccessFailed, describeDemoModes } from "./demoModes";

/**
 * Header indicator for local and simulated modes and for a failed CRM access
 * check. It sits in the header's fixed-height action cluster, so it appears
 * after `/api/health` answers without moving the page content.
 */
export function ModeBadge() {
  const { state } = useHealth();
  if (state.status !== "ready") return null;
  const notes = describeDemoModes(state.health.providers);
  const accessFailed = crmAccessFailed(state.health);
  if (notes.length === 0 && !accessFailed) return null;
  const title = accessFailed ? "CRM access failed" : "Demo mode";

  return (
    <Popover>
      <PopoverTrigger render={<Button variant="outline" size="xs" className="shrink-0" />}>
        <span
          aria-hidden
          className={cn("size-1.5 shrink-0 rounded-full", accessFailed ? "bg-destructive" : "bg-warning")}
        />
        {title}
      </PopoverTrigger>
      <PopoverPopup align="end" className="w-72 max-w-[calc(100vw-2rem)]">
        <div className="flex flex-col gap-2">
          <PopoverTitle className="text-sm font-medium">{title}</PopoverTitle>
          <PopoverDescription render={<div />} className="text-sm text-muted-foreground">
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
              {accessFailed ? (
                <li>
                  Confirmed inquiries are saved and stay queued until access is restored.
                </li>
              ) : null}
              {notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </PopoverDescription>
        </div>
      </PopoverPopup>
    </Popover>
  );
}

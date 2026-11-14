/*
 * Adapted from T3 Code (apps/web/src/components/RightPanelTabs.tsx,
 * RightPanelSheet.tsx, preview/PreviewPanelShell.tsx and
 * chat/PanelLayoutControls.tsx, MIT, (c) 2026 T3 Tools Inc.). RAG Support Assistant keeps
 * the panel frame, the tab bar, the inline/sheet switch at 980px and the
 * header toggle. Surfaces, tab closing, "add surface", maximizing and the
 * desktop title bar handling are not ported; tabs are a fixed list given by
 * the caller.
 */
import { PanelRightIcon } from "lucide-react";
import { useId, useRef } from "react";
import type { KeyboardEvent, ReactNode, Ref } from "react";

import { PreviewPanelShell } from "~/components/preview/PreviewPanelShell";
import { RightPanelSheet } from "~/components/RightPanelSheet";
import { SheetDescription, SheetHeader, SheetTitle } from "~/components/ui/sheet";
import { Toggle } from "~/components/ui/toggle";
import { Tooltip, TooltipPopup, TooltipTrigger } from "~/components/ui/tooltip";
import { useMediaQuery } from "~/hooks/useMediaQuery";
import { cn } from "~/lib/utils";
import { RIGHT_PANEL_INLINE_LAYOUT_MEDIA_QUERY } from "~/rightPanelLayout";

/** True when the right panel opens as a sheet over the page instead of beside it. */
export function useRightPanelSheetMode(): boolean {
  return useMediaQuery(RIGHT_PANEL_INLINE_LAYOUT_MEDIA_QUERY);
}

export interface RightPanelTab {
  id: string;
  title: string;
}

export function RightPanelToggle(props: {
  open: boolean;
  onToggle: () => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger render={<span className="flex shrink-0" />}>
        <Toggle
          className="shrink-0"
          pressed={props.open}
          onPressedChange={props.onToggle}
          aria-label={props.label}
          variant="ghost"
          size="sm"
          disabled={props.disabled}
        >
          <PanelRightIcon className="size-4" />
        </Toggle>
      </TooltipTrigger>
      <TooltipPopup side="bottom">{props.label}</TooltipPopup>
    </Tooltip>
  );
}

/** Position of the panel toggle: top right of the page, over the header row. */
export function RightPanelControls(props: { children: ReactNode }) {
  return (
    <div
      className="absolute top-[var(--workspace-controls-top)] right-[var(--workspace-controls-right)] z-50 mr-px flex h-[var(--workspace-topbar-height)] items-center gap-1"
      data-workspace-titlebar-controls
    >
      {props.children}
    </div>
  );
}

function RightPanelTabBar(props: {
  tabs: RightPanelTab[];
  activeTabId: string;
  onSelect: (id: string) => void;
  idPrefix: string;
  label: string;
  /** Controls rendered at the end of the bar; without them space is left for the page toggle. */
  layoutControls?: ReactNode;
}) {
  const listRef = useRef<HTMLDivElement | null>(null);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = props.tabs.findIndex((tab) => tab.id === props.activeTabId);
    let next = -1;
    if (event.key === "ArrowRight") next = (index + 1) % props.tabs.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + props.tabs.length) % props.tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = props.tabs.length - 1;
    const tab = props.tabs[next];
    if (!tab) return;
    event.preventDefault();
    props.onSelect(tab.id);
    listRef.current?.querySelector<HTMLElement>(`[data-tab-id="${tab.id}"]`)?.focus();
  };

  return (
    <div
      className={cn(
        "flex h-[var(--workspace-topbar-height)] min-h-[var(--workspace-topbar-height)] shrink-0 items-center gap-1 pl-2",
        props.layoutControls ? "pr-3" : "pr-12",
      )}
      data-right-panel-tabbar
    >
      <div
        ref={listRef}
        role="tablist"
        aria-label={props.label}
        className="flex h-full min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        onKeyDown={onKeyDown}
      >
        {props.tabs.map((tab) => {
          const active = tab.id === props.activeTabId;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`${props.idPrefix}-tab-${tab.id}`}
              aria-selected={active}
              aria-controls={`${props.idPrefix}-panel`}
              tabIndex={active ? 0 : -1}
              data-tab-id={tab.id}
              className={cn(
                "cursor-pointer group/tab flex h-6 max-w-36 shrink-0 items-center gap-0.5 rounded-md px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring",
                active
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
              )}
              onClick={() => props.onSelect(tab.id)}
            >
              <span className="truncate">{tab.title}</span>
            </button>
          );
        })}
      </div>
      {props.layoutControls}
    </div>
  );
}

/**
 * The right panel: beside the content on wide windows, a sheet from the right
 * on narrow ones. The caller owns `open` and renders the toggle.
 */
export function RightPanel(props: {
  open: boolean;
  onClose: () => void;
  /** Accessible name of the panel, for example "Sources and inquiry". */
  label: string;
  tabs: RightPanelTab[];
  activeTabId: string;
  onSelectTab: (id: string) => void;
  /** Rendered inside the sheet's tab bar, where the page toggle is covered. */
  sheetControls?: ReactNode;
  bodyRef?: Ref<HTMLDivElement>;
  children?: ReactNode;
}) {
  const sheetMode = useRightPanelSheetMode();
  const idPrefix = useId();

  // The shell must stay a direct child of the row: it measures its parent to clamp its width.
  const content = (mode: "inline" | "sheet") => (
    <PreviewPanelShell mode={mode}>
      <aside
        aria-label={mode === "inline" ? props.label : undefined}
        className="flex min-h-0 min-w-0 flex-1 flex-col"
      >
        <RightPanelTabBar
          tabs={props.tabs}
          activeTabId={props.activeTabId}
          onSelect={props.onSelectTab}
          idPrefix={idPrefix}
          label={props.label}
          layoutControls={
            mode === "sheet" && props.sheetControls ? (
              <div className="mr-px flex items-center">{props.sheetControls}</div>
            ) : undefined
          }
        />
        <div
          ref={props.bodyRef}
          role="tabpanel"
          id={`${idPrefix}-panel`}
          aria-labelledby={`${idPrefix}-tab-${props.activeTabId}`}
          tabIndex={-1}
          className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain outline-none"
          data-right-panel-surface-content
        >
          {props.children}
        </div>
      </aside>
    </PreviewPanelShell>
  );

  if (sheetMode) {
    return (
      <RightPanelSheet open={props.open} onClose={props.onClose}>
        <SheetHeader className="sr-only">
          <SheetTitle>{props.label}</SheetTitle>
          <SheetDescription>{props.label}</SheetDescription>
        </SheetHeader>
        {content("sheet")}
      </RightPanelSheet>
    );
  }

  if (!props.open) return null;
  return content("inline");
}

/*
 * Adapted from T3 Code (apps/web/src/components/AppSidebarLayout.tsx, MIT,
 * (c) 2026 T3 Tools Inc.). RAG Support Assistant keeps the shell composition (sidebar
 * provider, resizable off-canvas sidebar, fixed sidebar trigger) and drops the
 * desktop bridge, keybindings, settings navigation and thread state.
 */
import type { CSSProperties, ReactNode } from "react";

import { Sidebar, SidebarProvider, SidebarRail, SidebarTrigger } from "~/components/ui/sidebar";
import { Tooltip, TooltipPopup, TooltipTrigger } from "~/components/ui/tooltip";

const SIDEBAR_WIDTH_STORAGE_KEY = "rag-support-assistant:sidebar-width";
const SIDEBAR_DEFAULT_WIDTH = 16 * 16;
const SIDEBAR_MIN_WIDTH = 13 * 16;
const SIDEBAR_MAX_WIDTH = 26 * 16;
const MAIN_CONTENT_MIN_WIDTH = 40 * 16;

function SidebarControl() {
  return (
    // The right-side layout controls carry mr-px (border compensation inside
    // the panel), so the trigger mirrors it: both clusters sit one extra pixel
    // off their edge and the titlebar reads symmetric.
    <div
      className="pointer-events-none fixed left-[var(--workspace-controls-left)] top-[var(--workspace-controls-top)] z-50 ml-px flex h-[var(--workspace-topbar-height)] items-center"
      data-sidebar-control=""
    >
      <Tooltip>
        <TooltipTrigger
          render={<SidebarTrigger className="pointer-events-auto" aria-label="Toggle sidebar" />}
        />
        <TooltipPopup side="bottom">Toggle sidebar</TooltipPopup>
      </Tooltip>
    </div>
  );
}

export function AppShell(props: { sidebar: ReactNode; children: ReactNode }) {
  const style = { "--sidebar-width": `${SIDEBAR_DEFAULT_WIDTH}px` } as CSSProperties;
  return (
    <SidebarProvider className="h-dvh! min-h-0!" defaultOpen style={style}>
      <Sidebar
        side="left"
        collapsible="offcanvas"
        data-app-sidebar=""
        className="border-r border-sidebar-border bg-sidebar text-sidebar-foreground"
        resizable={{
          maxWidth: SIDEBAR_MAX_WIDTH,
          minWidth: SIDEBAR_MIN_WIDTH,
          shouldAcceptWidth: ({ currentWidth, nextWidth, wrapper }) =>
            nextWidth <= currentWidth || wrapper.clientWidth - nextWidth >= MAIN_CONTENT_MIN_WIDTH,
          storageKey: SIDEBAR_WIDTH_STORAGE_KEY,
        }}
      >
        {props.sidebar}
        <SidebarRail />
      </Sidebar>
      {props.children}
      <SidebarControl />
    </SidebarProvider>
  );
}

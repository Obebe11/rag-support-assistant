import { Outlet } from "react-router";

import { AppShell } from "~/components/AppShell";
import { SidebarInset } from "~/components/ui/sidebar";

import { ChatProvider } from "../features/chat/ChatProvider";
import { AppSidebar } from "./AppSidebar";

/** The shared frame: sidebar on the left, the current page in the main area. */
export function AppLayout() {
  return (
    <ChatProvider>
      <a
        href="#main"
        className="sr-only z-[200] rounded-md bg-background px-3 py-2 text-sm font-medium text-foreground shadow-md ring-2 ring-ring focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Skip to content
      </a>
      <AppShell sidebar={<AppSidebar />}>
        <SidebarInset
          id="main"
          tabIndex={-1}
          className="h-svh min-h-0 overflow-hidden overscroll-y-none bg-background text-foreground outline-none md:h-dvh"
        >
          <Outlet />
        </SidebarInset>
      </AppShell>
    </ChatProvider>
  );
}

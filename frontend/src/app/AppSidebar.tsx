import { ArrowLeftIcon, MessageSquareIcon, SettingsIcon, SquarePenIcon } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router";

import {
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarTrigger,
  useSidebar,
} from "~/components/ui/sidebar";
import { Skeleton } from "~/components/ui/skeleton";
import { cn } from "~/lib/utils";

import { useChatContext } from "../features/chat/ChatProvider";
import { useHealth } from "../hooks/useHealth";
import { modeRows } from "./demoModes";

function SectionLabel(props: { id: string; children: string }) {
  return (
    <div className="mb-1 mt-3 flex w-full items-center gap-2 px-2.5 text-left">
      <h2 id={props.id} className="text-xs font-medium text-muted-foreground/50">
        {props.children}
      </h2>
      <span aria-hidden className="h-px flex-1 bg-sidebar-border/60" />
    </div>
  );
}

function DemoStatus() {
  const { state } = useHealth();

  if (state.status === "loading") {
    return (
      <div className="flex flex-col gap-px" aria-busy="true" aria-label="Loading demo status">
        {[0, 1, 2].map((row) => (
          <div key={row} className="flex h-9 items-center px-2.5">
            <Skeleton className="h-3.5 w-full" />
          </div>
        ))}
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <p className="m-0 flex min-h-9 items-center px-2.5 text-sm text-muted-foreground">
        Status unavailable: the server did not answer.
      </p>
    );
  }

  const rows = modeRows(state.health);
  const databaseOk = state.health.database === "ok";
  return (
    <dl className="m-0 flex flex-col gap-px">
      {rows.map((row) => (
        <div key={row.name} className="flex h-9 items-center gap-2.5 px-2.5 text-sm">
          <span
            aria-hidden
            className={cn("size-1.5 shrink-0 rounded-full", row.live ? "bg-success" : "bg-warning")}
          />
          <dt className="shrink-0 text-sidebar-foreground">{row.name}</dt>
          <dd className="m-0 min-w-0 flex-1 truncate text-right text-muted-foreground">{row.value}</dd>
        </div>
      ))}
      {databaseOk ? null : (
        <div className="flex h-9 items-center gap-2.5 px-2.5 text-sm">
          <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-destructive" />
          <dt className="shrink-0 text-sidebar-foreground">Database</dt>
          <dd className="m-0 min-w-0 flex-1 truncate text-right text-muted-foreground">Unavailable</dd>
        </div>
      )}
    </dl>
  );
}

/** Left panel: new conversation, the current one, what the demo runs on, and the way to admin. */
export function AppSidebar() {
  const chat = useChatContext();
  const { isMobile, setOpenMobile } = useSidebar();
  const location = useLocation();
  const navigate = useNavigate();
  const onAdmin = location.pathname.startsWith("/admin");
  const onChat = location.pathname === "/";

  const closeOnMobile = () => {
    if (isMobile) setOpenMobile(false);
  };

  // The conversation is listed once it has a message; before that "New conversation" would name it twice.
  const conversationTitle =
    chat.messages.find((message) => message.role === "user")?.content ?? chat.pending?.content ?? null;

  const rowClass = (active: boolean) =>
    cn(
      "group/sidebar-row relative flex h-9 w-full cursor-pointer items-center gap-2.5 overflow-hidden rounded-md px-2.5 text-left text-sm outline-none select-none focus-visible:ring-2 focus-visible:ring-ring",
      active
        ? "bg-sidebar-row-active text-sidebar-foreground"
        : "bg-transparent text-sidebar-foreground hover:bg-sidebar-row-hover",
    );

  return (
    <>
      <SidebarHeader className="relative h-[var(--workspace-topbar-height)] shrink-0 flex-row items-center px-3 py-0 md:px-0">
        <SidebarTrigger className="relative z-10 md:hidden" aria-label="Close sidebar" />
        <Link
          to="/"
          onClick={closeOnMobile}
          className="relative z-10 flex h-7 w-fit min-w-0 shrink-0 items-center gap-1 overflow-hidden rounded-md px-1 text-foreground outline-hidden ring-ring focus-visible:ring-2 md:ml-[var(--workspace-titlebar-content-left)] md:px-0"
        >
          <span className="-translate-y-px truncate text-sm font-medium tracking-tight">Northline</span>
          <span className="-translate-y-px truncate text-sm font-medium tracking-tight text-muted-foreground">
            Support
          </span>
        </Link>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup className="relative z-[1] gap-1 p-[var(--sidebar-content-inset)]">
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                onClick={() => {
                  chat.startNew();
                  closeOnMobile();
                  if (!onChat) void navigate("/");
                }}
              >
                <SquarePenIcon />
                <span>New conversation</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>

          {conversationTitle === null ? null : (
            <nav aria-labelledby="sidebar-conversation">
              <SectionLabel id="sidebar-conversation">Conversation</SectionLabel>
              <div className="flex flex-col gap-px">
                <Link
                  to="/"
                  onClick={closeOnMobile}
                  aria-current={onChat ? "page" : undefined}
                  className={rowClass(onChat)}
                >
                  <MessageSquareIcon aria-hidden className="size-4 shrink-0 text-icon-muted" />
                  <span className="min-w-0 flex-1 truncate">{conversationTitle}</span>
                </Link>
              </div>
            </nav>
          )}

          <section aria-labelledby="sidebar-demo-status">
            <SectionLabel id="sidebar-demo-status">Demo status</SectionLabel>
            <DemoStatus />
          </section>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="p-[var(--sidebar-content-inset)]">
        <p className="m-0 px-2.5 pb-1 text-xs leading-relaxed text-muted-foreground">
          Handoff AI demo. Northline Office Equipment is a fictional company.
        </p>
        <SidebarMenu>
          <SidebarMenuItem>
            {onAdmin ? (
              <SidebarMenuButton render={<Link to="/" onClick={closeOnMobile} />}>
                <ArrowLeftIcon />
                <span>Back to chat</span>
              </SidebarMenuButton>
            ) : (
              <SidebarMenuButton render={<Link to="/admin" onClick={closeOnMobile} />}>
                <SettingsIcon />
                <span>Admin</span>
              </SidebarMenuButton>
            )}
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </>
  );
}

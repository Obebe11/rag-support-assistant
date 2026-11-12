import { CircleAlertIcon, XIcon } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import { RightPanel, RightPanelControls, useRightPanelSheetMode } from "~/components/RightPanel";
import { Alert, AlertDescription, AlertTitle } from "~/components/ui/alert";
import { Button } from "~/components/ui/button";
import { cn } from "~/lib/utils";

import type { AdminApi, DocumentRead } from "../api/client";
import { HealthBanner } from "../app/HealthBanner";
import { PageHeader } from "../app/PageHeader";
import { DeliveryLogPanel } from "../features/admin/DeliveryLogPanel";
import { DeleteDialog, UploadDialog } from "../features/admin/DocumentDialogs";
import { DocumentsView } from "../features/admin/DocumentsView";
import { formatDateTime } from "../features/admin/format";
import { InquiriesView } from "../features/admin/InquiriesView";
import { TokenForm } from "../features/admin/TokenForm";
import { useAdminInquiries } from "../features/admin/useAdminInquiries";
import { useAdminSession } from "../features/admin/useAdminSession";
import type { AdminSession } from "../features/admin/useAdminSession";
import { useDocuments } from "../features/admin/useDocuments";
import { VersionsPanel } from "../features/admin/VersionsPanel";
import { useHealth } from "../hooks/useHealth";

type AdminView = "documents" | "inquiries";

const VIEWS: { id: AdminView; title: string }[] = [
  { id: "documents", title: "Documents" },
  { id: "inquiries", title: "Inquiries" },
];

type DialogState =
  | { type: "upload" }
  | { type: "replace"; document: DocumentRead }
  | { type: "delete"; document: DocumentRead }
  | null;

function countLabel(total: number, singular: string, plural: string): string {
  return `${total} ${total === 1 ? singular : plural}`;
}

/** The side panel shows the versions of a document or the delivery log of an inquiry. */
type AdminPanel = { type: "versions"; id: string } | { type: "delivery"; id: string } | null;

/** The raw result of a failed CRM access check. It is technical, so it is shown here and not to visitors. */
function CrmAccessAlert() {
  const { state } = useHealth();
  const access = state.status === "ready" ? state.health.providers.crm.access : null;
  if (!access || access.state !== "failed") return null;
  return (
    <Alert variant="error" controlAlignment="first-line" className="mb-3 mt-1">
      <CircleAlertIcon aria-hidden />
      <AlertTitle>CRM access check failed</AlertTitle>
      <AlertDescription>
        {access.message ? <span className="[overflow-wrap:anywhere]">{access.message}</span> : null}
        <span>
          Confirmed inquiries stay queued and can be sent again after access is restored.
          {access.checked_at ? ` Checked ${formatDateTime(access.checked_at)}.` : ""}
        </span>
      </AlertDescription>
    </Alert>
  );
}

/** Below this content width the tables become stacked cards. */
const TABLE_MIN_WIDTH = 760;

function AdminWorkspace({ session, client }: { session: AdminSession; client: AdminApi }) {
  const documents = useDocuments(client, session.handleAuthError);
  const inquiries = useAdminInquiries(client, session.handleAuthError);
  const sheetMode = useRightPanelSheetMode();
  const contentRef = useRef<HTMLDivElement | null>(null);
  const [contentWidth, setContentWidth] = useState<number | null>(null);
  // The sidebar and the versions panel both narrow the content, so measure it instead of the window.
  useEffect(() => {
    const content = contentRef.current;
    if (!content || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setContentWidth(content.clientWidth));
    observer.observe(content);
    return () => observer.disconnect();
  }, []);
  const compact = contentWidth === null ? sheetMode : contentWidth < TABLE_MIN_WIDTH;
  const tabsId = useId();
  const tabListRef = useRef<HTMLDivElement | null>(null);
  const [view, setView] = useState<AdminView>("documents");
  const [dialog, setDialog] = useState<DialogState>(null);
  const [panel, setPanel] = useState<AdminPanel>(null);
  const [notice, setNotice] = useState("");

  // Read the record from its list, so the panel follows progress and closes after a delete.
  const versionsDocument =
    view === "documents" && panel?.type === "versions"
      ? (documents.items.find((document) => document.id === panel.id) ?? null)
      : null;
  const deliveryInquiry =
    view === "inquiries" && panel?.type === "delivery"
      ? (inquiries.items.find((inquiry) => inquiry.id === panel.id) ?? null)
      : null;
  const panelOpen = versionsDocument !== null || deliveryInquiry !== null;
  const closePanel = () => setPanel(null);

  const onTabKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const next: AdminView = view === "documents" ? "inquiries" : "documents";
    setView(next);
    tabListRef.current?.querySelector<HTMLElement>(`[data-view="${next}"]`)?.focus();
  };

  const closeButton = (
    <Button variant="ghost" size="icon-sm" aria-label="Close side panel" onClick={closePanel}>
      <XIcon />
    </Button>
  );

  const loaded = view === "documents" ? documents.status === "ready" : inquiries.status === "ready";
  const summary =
    view === "documents"
      ? countLabel(documents.total, "document", "documents")
      : countLabel(inquiries.total, "inquiry", "inquiries");

  return (
    <>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-x-hidden">
        <PageHeader
          title="Admin"
          reserveToggleSpace={false}
          actions={
            <Button variant="ghost" size="xs" onClick={() => session.signOut()}>
              Sign out
            </Button>
          }
        />
        <div className="relative flex min-h-0 flex-1 flex-col">
          <HealthBanner placement="inline" />
          <div className="flex min-h-10 shrink-0 flex-wrap items-center gap-x-3 gap-y-2 px-3 pb-2 sm:px-5">
            <div
              ref={tabListRef}
              role="tablist"
              aria-label="Admin sections"
              className="flex items-center gap-1"
              onKeyDown={onTabKeyDown}
            >
              {VIEWS.map((item) => {
                const active = item.id === view;
                return (
                  <button
                    key={item.id}
                    type="button"
                    role="tab"
                    id={`${tabsId}-tab-${item.id}`}
                    aria-selected={active}
                    aria-controls={`${tabsId}-panel`}
                    tabIndex={active ? 0 : -1}
                    data-view={item.id}
                    className={cn(
                      "flex h-7 cursor-pointer items-center rounded-md px-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      active
                        ? "bg-accent text-foreground"
                        : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                    )}
                    onClick={() => setView(item.id)}
                  >
                    {item.title}
                  </button>
                );
              })}
            </div>
            {/* On narrow windows the summary takes its own row under the tabs. */}
            <p
              className="order-last m-0 w-full min-w-0 text-xs text-muted-foreground tabular-nums sm:order-none sm:w-auto sm:flex-1"
              role="status"
            >
              {loaded ? summary : ""}
              {notice !== "" && view === "documents" ? `${loaded ? ". " : ""}${notice}` : ""}
            </p>
            <span aria-hidden className="flex-1 sm:hidden" />
            {view === "documents" ? (
              <Button size="sm" onClick={() => setDialog({ type: "upload" })}>
                Upload document
              </Button>
            ) : null}
          </div>
          <div
            ref={contentRef}
            role="tabpanel"
            id={`${tabsId}-panel`}
            aria-labelledby={`${tabsId}-tab-${view}`}
            className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-8 sm:px-5"
          >
            <CrmAccessAlert />
            {view === "documents" ? (
              <DocumentsView
                documents={documents}
                compact={compact}
                actions={{
                  onUpload: () => setDialog({ type: "upload" }),
                  onVersions: (document) => setPanel({ type: "versions", id: document.id }),
                  onReplace: (document) => setDialog({ type: "replace", document }),
                  onDelete: (document) => setDialog({ type: "delete", document }),
                }}
              />
            ) : (
              <InquiriesView
                inquiries={inquiries}
                compact={compact}
                onOpenLog={(inquiry) => setPanel({ type: "delivery", id: inquiry.id })}
              />
            )}
          </div>
        </div>
      </div>

      <RightPanel
        open={panelOpen}
        onClose={closePanel}
        label={deliveryInquiry ? "Delivery log" : "Document versions"}
        tabs={[deliveryInquiry ? { id: "panel", title: "Delivery log" } : { id: "panel", title: "Versions" }]}
        activeTabId="panel"
        onSelectTab={() => undefined}
        sheetControls={closeButton}
      >
        {versionsDocument ? (
          <VersionsPanel document={versionsDocument} loadVersions={documents.loadVersions} />
        ) : null}
        {deliveryInquiry ? <DeliveryLogPanel inquiry={deliveryInquiry} /> : null}
      </RightPanel>
      {panelOpen && !sheetMode ? <RightPanelControls>{closeButton}</RightPanelControls> : null}

      {dialog?.type === "upload" ? (
        <UploadDialog
          replaceTarget={null}
          onClose={() => setDialog(null)}
          onSubmit={async (input) => {
            const failure = await documents.upload(input);
            if (failure === null) setNotice("Document uploaded. The assistant cites it after indexing.");
            return failure;
          }}
        />
      ) : null}
      {dialog?.type === "replace" ? (
        <UploadDialog
          replaceTarget={dialog.document}
          onClose={() => setDialog(null)}
          onSubmit={async (input) => {
            const failure = await documents.replace(dialog.document.id, input);
            if (failure === null) setNotice("New version uploaded. The assistant cites it after indexing.");
            return failure;
          }}
        />
      ) : null}
      {dialog?.type === "delete" ? (
        <DeleteDialog
          target={dialog.document}
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            const failure = await documents.remove(dialog.document.id);
            if (failure === null) setNotice("Document deleted.");
            return failure;
          }}
        />
      ) : null}
    </>
  );
}

/** Admin: documents and inquiries behind the admin token. */
export function AdminPage() {
  const session = useAdminSession();

  return (
    <div className="relative flex min-h-0 min-w-0 flex-1 overflow-hidden bg-background">
      {session.client ? (
        <AdminWorkspace session={session} client={session.client} />
      ) : (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-x-hidden">
          <PageHeader title="Admin" />
          <div className="relative flex min-h-0 flex-1 flex-col overflow-y-auto">
            <HealthBanner />
            <TokenForm session={session} />
          </div>
        </div>
      )}
    </div>
  );
}

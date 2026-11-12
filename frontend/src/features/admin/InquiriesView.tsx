import { CircleAlertIcon } from "lucide-react";

import { Alert, AlertAction, AlertDescription, AlertTitle } from "~/components/ui/alert";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "~/components/ui/empty";
import { Skeleton } from "~/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "~/components/ui/table";

import type { InquiryRead } from "../../api/client";
import { describeDelivery, describeFailureReason } from "../inquiry/deliveryStatus";
import type { DeliveryPhase } from "../inquiry/deliveryStatus";
import { EmailText } from "../inquiry/EmailText";
import { formatDateTime } from "./format";
import type { StatusVariant } from "./format";
import type { AdminInquiries } from "./useAdminInquiries";

export const PHASE_VARIANT: Record<DeliveryPhase, StatusVariant> = {
  queued: "info",
  sending: "info",
  retrying: "warning",
  delivered: "success",
  failed: "error",
};

export function kindLabel(inquiry: InquiryRead): string {
  return inquiry.kind === "handoff" ? "Human handoff" : "Purchase";
}

function Contact({ inquiry }: { inquiry: InquiryRead }) {
  const { name, email } = inquiry.contact;
  if (!name && !email) return <span className="text-muted-foreground">Not given yet</span>;
  return (
    <div className="min-w-0">
      <div className="text-foreground [overflow-wrap:anywhere]">{name ?? "No name"}</div>
      {email ? (
        <div className="text-xs text-muted-foreground [overflow-wrap:anywhere]">
          <EmailText email={email} />
        </div>
      ) : null}
    </div>
  );
}

function Request({ inquiry }: { inquiry: InquiryRead }) {
  if (inquiry.kind === "handoff") {
    return <span className="line-clamp-2 [overflow-wrap:anywhere]">{inquiry.notes ?? "No question yet"}</span>;
  }
  const details = [
    inquiry.quantity != null ? `quantity ${inquiry.quantity}` : null,
    inquiry.timeline ?? null,
  ].filter(Boolean);
  return (
    <div className="min-w-0">
      <div className="text-foreground [overflow-wrap:anywhere]">{inquiry.product ?? "No product yet"}</div>
      {details.length > 0 ? (
        <div className="text-xs text-muted-foreground [overflow-wrap:anywhere]">{details.join(", ")}</div>
      ) : null}
    </div>
  );
}

/** Badge variant and label of a delivery; a simulated delivery never reads as delivered to a CRM. */
export function deliveryBadge(inquiry: InquiryRead): { label: string; variant: StatusVariant } {
  const delivery = inquiry.delivery ?? null;
  const view = describeDelivery(delivery, inquiry.kind);
  const simulatedDone = view.phase === "delivered" && delivery !== null && !delivery.live;
  // The visitor wording "Not delivered" is the admin's "Delivery failed".
  const label = view.phase === "failed" && delivery?.live ? "Delivery failed" : view.label;
  return { label, variant: simulatedDone ? "warning" : PHASE_VARIANT[view.phase] };
}

/** Delivery status with the technical error, and the way to the attempt log. */
function Delivery({ inquiry, onOpenLog }: { inquiry: InquiryRead; onOpenLog: (inquiry: InquiryRead) => void }) {
  if (inquiry.status !== "confirmed") {
    return <span className="text-muted-foreground">Not confirmed</span>;
  }
  const delivery = inquiry.delivery ?? null;
  const badge = deliveryBadge(inquiry);
  const attempts = delivery?.attempt_count ?? 0;
  const unfinished = delivery?.status === "failed" || (delivery?.status === "pending" && attempts > 0);
  const reason = delivery ? describeFailureReason(delivery) : null;
  return (
    <div className="flex min-w-0 flex-col items-start gap-1">
      <Badge variant={badge.variant}>{badge.label}</Badge>
      {attempts > 0 ? (
        <span className="text-xs text-muted-foreground tabular-nums">
          {attempts === 1 ? "1 attempt" : `${attempts} attempts`}
          {delivery && !delivery.live && delivery.status !== "delivered" ? ", simulated CRM" : ""}
        </span>
      ) : null}
      {reason ? (
        <p className="m-0 max-w-72 text-xs whitespace-normal text-muted-foreground">{reason}</p>
      ) : null}
      {unfinished && delivery?.last_error ? (
        <p className="m-0 max-w-prose text-xs whitespace-normal text-destructive-foreground [overflow-wrap:anywhere]">
          {delivery.last_error}
        </p>
      ) : null}
      <Button variant="ghost" size="xs" className="-ml-1.5" onClick={() => onOpenLog(inquiry)}>
        Delivery log <span className="sr-only">for {inquiry.contact.name ?? kindLabel(inquiry)}</span>
      </Button>
    </div>
  );
}

export function InquiriesView(props: {
  inquiries: AdminInquiries;
  compact: boolean;
  onOpenLog: (inquiry: InquiryRead) => void;
}) {
  const { inquiries } = props;

  if (inquiries.status === "loading") {
    return (
      <div className="flex flex-col gap-2 pt-2" aria-busy="true" aria-label="Loading inquiries">
        {[0, 1, 2, 3].map((row) => (
          <Skeleton key={row} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (inquiries.status === "error" && inquiries.loadError) {
    return (
      <Alert variant="error" className="mt-2">
        <CircleAlertIcon aria-hidden />
        <AlertTitle>{inquiries.loadError.title}</AlertTitle>
        <AlertDescription>{inquiries.loadError.message}</AlertDescription>
        <AlertAction>
          <Button variant="outline" size="xs" onClick={inquiries.reload}>
            Try again
          </Button>
        </AlertAction>
      </Alert>
    );
  }

  if (inquiries.items.length === 0) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle className="text-base font-medium">No inquiries yet</EmptyTitle>
          <EmptyDescription>
            Purchase inquiries and human handoff requests from the chat appear here.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  if (props.compact) {
    return (
      <ul className="m-0 flex list-none flex-col gap-3 p-0 pt-2">
        {inquiries.items.map((inquiry) => (
          <li key={inquiry.id} className="rounded-xl border border-border/60 bg-card/50 p-3">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <h3 className="m-0 text-sm font-medium text-foreground">{kindLabel(inquiry)}</h3>
              <span className="text-xs text-muted-foreground tabular-nums">
                {formatDateTime(inquiry.created_at)}
              </span>
            </div>
            <dl className="m-0 mt-2.5 flex flex-col gap-1.5 text-sm">
              <div className="flex gap-3">
                <dt className="w-20 shrink-0 text-muted-foreground">Contact</dt>
                <dd className="m-0 min-w-0 flex-1">
                  <Contact inquiry={inquiry} />
                </dd>
              </div>
              <div className="flex gap-3">
                <dt className="w-20 shrink-0 text-muted-foreground">Request</dt>
                <dd className="m-0 min-w-0 flex-1">
                  <Request inquiry={inquiry} />
                </dd>
              </div>
              <div className="flex gap-3">
                <dt className="w-20 shrink-0 text-muted-foreground">Delivery</dt>
                <dd className="m-0 min-w-0 flex-1">
                  <Delivery inquiry={inquiry} onOpenLog={props.onOpenLog} />
                </dd>
              </div>
            </dl>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <Table className="text-sm">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="text-muted-foreground">Received</TableHead>
          <TableHead className="text-muted-foreground">Type</TableHead>
          <TableHead className="text-muted-foreground">Contact</TableHead>
          <TableHead className="text-muted-foreground">Request</TableHead>
          <TableHead className="text-muted-foreground">Delivery</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {inquiries.items.map((inquiry) => (
          <TableRow key={inquiry.id}>
            <TableCell className="align-top text-muted-foreground tabular-nums">
              {formatDateTime(inquiry.created_at)}
            </TableCell>
            <TableCell className="align-top">{kindLabel(inquiry)}</TableCell>
            <TableCell className="max-w-56 align-top whitespace-normal">
              <Contact inquiry={inquiry} />
            </TableCell>
            <TableCell className="max-w-72 align-top whitespace-normal">
              <Request inquiry={inquiry} />
            </TableCell>
            <TableCell className="align-top whitespace-normal">
              <Delivery inquiry={inquiry} onOpenLog={props.onOpenLog} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

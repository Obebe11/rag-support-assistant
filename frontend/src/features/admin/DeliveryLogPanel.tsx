import type { ReactNode } from "react";

import { Badge } from "~/components/ui/badge";

import type { InquiryRead } from "../../api/client";
import { describeFailureReason } from "../inquiry/deliveryStatus";
import { formatDateTime } from "./format";
import { deliveryBadge, kindLabel } from "./InquiriesView";

function Fact(props: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3 border-b border-border/60 py-2 text-sm last:border-b-0">
      <dt className="w-28 shrink-0 text-muted-foreground">{props.label}</dt>
      <dd className="m-0 min-w-0 flex-1 text-foreground [overflow-wrap:anywhere]">{props.children}</dd>
    </div>
  );
}

/**
 * Delivery of one inquiry for the administrator: where it went, why it
 * stopped, and every recorded attempt with its technical error. Visitors
 * never see this text.
 */
export function DeliveryLogPanel({ inquiry }: { inquiry: InquiryRead }) {
  const delivery = inquiry.delivery ?? null;
  const badge = deliveryBadge(inquiry);
  const attempts = delivery?.attempts ?? [];
  const counted = delivery?.attempt_count ?? 0;
  const reason = delivery ? describeFailureReason(delivery) : null;
  const waitingForRetry = delivery?.status === "pending" && counted > 0;

  return (
    <section className="px-4 pb-6 pt-1 sm:px-5" aria-label="Delivery log">
      <h2 className="m-0 text-sm font-medium text-foreground [overflow-wrap:anywhere]">
        {kindLabel(inquiry)}: {inquiry.contact.name ?? "no name"}
      </h2>
      <p className="m-0 mt-1 text-xs leading-relaxed text-muted-foreground">
        Confirmed {formatDateTime(inquiry.confirmed_at)}
      </p>

      <dl className="m-0 mt-4 flex flex-col rounded-xl border border-border/60 bg-card/50 px-3">
        <Fact label="Status">
          <Badge variant={badge.variant}>{badge.label}</Badge>
        </Fact>
        <Fact label="Destination">
          {delivery === null
            ? "Not known yet"
            : delivery.live
              ? "Live CRM"
              : "Simulated CRM. No CRM record exists."}
        </Fact>
        {reason ? <Fact label="Why it stopped">{reason}</Fact> : null}
        {waitingForRetry && delivery?.next_attempt_at ? (
          <Fact label="Next attempt">{formatDateTime(delivery.next_attempt_at)}</Fact>
        ) : null}
        {delivery?.last_error && delivery.status !== "delivered" ? (
          <Fact label="Last error">
            <span className="text-destructive-foreground">{delivery.last_error}</span>
          </Fact>
        ) : null}
        {delivery?.delivered_at ? <Fact label="Delivered">{formatDateTime(delivery.delivered_at)}</Fact> : null}
        {delivery?.crm_record_id ? <Fact label="CRM record">{delivery.crm_record_id}</Fact> : null}
        {delivery?.crm_contact_id ? <Fact label="CRM contact">{delivery.crm_contact_id}</Fact> : null}
      </dl>

      <h3 className="m-0 mt-5 text-xs font-medium text-muted-foreground">Attempts</h3>
      {attempts.length === 0 ? (
        <p className="m-0 mt-1.5 text-sm text-muted-foreground">No attempt has finished yet.</p>
      ) : (
        <ol className="m-0 mt-1.5 flex list-none flex-col gap-2 p-0">
          {attempts.map((attempt) => (
            <li key={attempt.attempt_number} className="rounded-xl border border-border/60 bg-card/50 p-3">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-sm font-medium text-foreground tabular-nums">
                  Attempt {attempt.attempt_number}
                </span>
                <Badge variant={attempt.outcome === "succeeded" ? "success" : "error"}>
                  {attempt.outcome === "succeeded" ? "Succeeded" : "Failed"}
                </Badge>
                <span className="text-xs text-muted-foreground tabular-nums">
                  {formatDateTime(attempt.finished_at)}
                </span>
              </div>
              {attempt.error ? (
                <p className="m-0 mt-1.5 text-xs text-destructive-foreground [overflow-wrap:anywhere]">
                  {attempt.error}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      )}
      {counted > attempts.length ? (
        <p className="m-0 mt-2 text-xs leading-relaxed text-muted-foreground">
          {counted} attempts were started. An attempt that was cut short, or is still running, has no entry.
        </p>
      ) : null}
    </section>
  );
}

import type { DeliveryRead, InquiryKind } from "../../api/client";

export type DeliveryPhase = "queued" | "sending" | "retrying" | "delivered" | "failed";

export interface DeliveryView {
  phase: DeliveryPhase;
  /** Short status name, also used in the admin list. */
  label: string;
  /** One sentence on what this means for the person who sent the inquiry. */
  detail: string;
}

/**
 * `pending` covers two situations in the contract: queued before the first
 * attempt, and waiting for an automatic retry after a failed one.
 */
export function deliveryPhase(delivery: DeliveryRead | null): DeliveryPhase {
  if (delivery === null) return "queued";
  switch (delivery.status) {
    case "delivered":
      return "delivered";
    case "failed":
      return "failed";
    case "in_progress":
      return "sending";
    default:
      return delivery.attempt_count > 0 ? "retrying" : "queued";
  }
}

const noun = (kind: InquiryKind) => (kind === "handoff" ? "request" : "inquiry");

/**
 * Words for a delivery status. A simulated delivery never reads as a CRM
 * record: `live: false` changes the label and the explanation.
 */
export function describeDelivery(delivery: DeliveryRead | null, kind: InquiryKind): DeliveryView {
  const phase = deliveryPhase(delivery);
  const simulated = delivery !== null && !delivery.live;
  const attempts = delivery?.attempt_count ?? 0;
  switch (phase) {
    case "queued":
      return {
        phase,
        label: "Queued",
        detail: `Your ${noun(kind)} is confirmed and waiting to be sent.`,
      };
    case "sending":
      return {
        phase,
        label: "Sending",
        detail: attempts > 1 ? `Attempt ${attempts} is in progress.` : "Delivery is in progress.",
      };
    case "retrying":
      return {
        phase,
        label: "Retrying",
        detail: `Attempt ${attempts} did not succeed. The next attempt starts automatically.`,
      };
    case "delivered":
      return simulated
        ? {
            phase,
            label: "Delivery simulated",
            detail: `Demo mode: no CRM is connected, so no CRM record was created and nobody receives this ${noun(kind)}.`,
          }
        : {
            phase,
            label: "Delivered",
            detail: `Your ${noun(kind)} is recorded in the Northline CRM.`,
          };
    case "failed":
      return {
        phase,
        label: simulated ? "Simulated delivery failed" : "Not delivered",
        // The technical error (`last_error`) is for the admin view, not for the visitor.
        detail:
          delivery?.failure_reason === "permanent_error"
            ? `Your ${noun(kind)} is saved, but it could not be delivered. You can send it again; it may fail the same way until the problem is fixed on our side.`
            : `Your ${noun(kind)} is saved, but it was not delivered${attempts > 1 ? ` after ${attempts} attempts` : ""}. You can send it again.`,
      };
  }
}

/** Why a delivery stopped, in words for the admin list. */
export function describeFailureReason(delivery: DeliveryRead): string | null {
  if (delivery.status !== "failed") return null;
  switch (delivery.failure_reason) {
    case "permanent_error":
      return "The CRM rejected the request. A retry fails the same way until the cause is fixed.";
    case "attempts_exhausted":
      return "No automatic attempt is left. Each one hit a temporary error.";
    default:
      return null;
  }
}

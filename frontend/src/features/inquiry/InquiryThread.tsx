import { createPortal } from "react-dom";

import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";

import type { InquiryKind, InquiryRead } from "../../api/client";
import { useHealth } from "../../hooks/useHealth";
import { describeDelivery } from "./deliveryStatus";
import type { DeliveryPhase } from "./deliveryStatus";
import { FIELD_LABELS, REQUIRED_BY_KIND } from "./inquiryForm";
import type { InquiryValues } from "./inquiryForm";
import { InquiryPanel, inquiryTitle } from "./InquiryPanel";
import { useInquiryFlow } from "./useInquiryFlow";
import type { InquiryFlow } from "./useInquiryFlow";

type BadgeVariant = "outline" | "info" | "warning" | "success" | "error";

const PHASE_BADGE: Record<DeliveryPhase, BadgeVariant> = {
  queued: "info",
  sending: "info",
  retrying: "warning",
  delivered: "success",
  failed: "error",
};

function cardStatus(flow: InquiryFlow): { label: string; variant: BadgeVariant } {
  if (flow.step === "form") return { label: "Draft", variant: "outline" };
  if (flow.step === "preview") return { label: "Ready to confirm", variant: "info" };
  const view = describeDelivery(flow.delivery, flow.kind);
  const simulatedDone = view.phase === "delivered" && flow.delivery !== null && !flow.delivery.live;
  return { label: view.label, variant: simulatedDone ? "warning" : PHASE_BADGE[view.phase] };
}

function openLabel(flow: InquiryFlow): string {
  if (flow.step === "status") return "View delivery status";
  if (flow.step === "preview") return "Open review";
  return flow.kind === "handoff" ? "Open request form" : "Open inquiry form";
}

function summaryLine(flow: InquiryFlow): string {
  const { values, kind } = flow;
  if (kind === "handoff") return values.notes.trim();
  const product = values.product.trim() === "" ? "Product not chosen yet" : values.product.trim();
  return values.quantity.trim() === "" ? product : `${product}, quantity ${values.quantity.trim()}`;
}

/** The card in the timeline for one inquiry. It follows the flow, so the status is live. */
function InquiryCard(props: { flow: InquiryFlow; started: boolean; simulated: boolean; onOpen: () => void }) {
  const { flow } = props;

  if (flow.kind === "handoff" && !props.started) {
    return (
      <div className="mt-3 flex flex-col items-start gap-2.5 rounded-xl border border-border/60 bg-card/50 p-3">
        <Button variant="outline" size="sm" onClick={props.onOpen}>
          {props.simulated ? "Try simulated handoff" : "Talk to a person"}
        </Button>
      </div>
    );
  }

  const status = cardStatus(flow);
  const missing =
    flow.step === "form" ? REQUIRED_BY_KIND[flow.kind].filter((field) => flow.values[field].trim() === "") : [];
  const view = flow.step === "status" ? describeDelivery(flow.delivery, flow.kind) : null;

  return (
    <div className="mt-3 flex flex-col items-start gap-2 rounded-xl border border-border/60 bg-card/50 p-3">
      <div className="flex w-full flex-wrap items-center gap-x-2 gap-y-1">
        <h3 className="m-0 text-sm font-medium text-foreground">
          {flow.kind === "handoff" && !props.simulated
            ? "Question for the Northline team"
            : inquiryTitle(flow.kind, props.simulated)}
        </h3>
        <Badge variant={status.variant}>{status.label}</Badge>
      </div>
      <p className="m-0 line-clamp-2 text-sm leading-relaxed text-foreground/80 [overflow-wrap:anywhere]">
        {summaryLine(flow)}
      </p>
      {missing.length > 0 ? (
        <p className="m-0 text-xs leading-relaxed text-muted-foreground">
          Still needed: {missing.map((field) => FIELD_LABELS[flow.kind][field].toLowerCase()).join(", ")}.
        </p>
      ) : null}
      {view ? <p className="m-0 text-xs leading-relaxed text-muted-foreground">{view.detail}</p> : null}
      <Button variant="outline" size="sm" className="mt-0.5" onClick={props.onOpen}>
        {openLabel(flow)}
      </Button>
    </div>
  );
}

/**
 * One inquiry in the conversation: the card in the timeline and, while it is
 * the one shown in the side panel, the form, review and status there. Both
 * read the same flow, so the card stays current when the panel is closed.
 */
export function InquiryThread(props: {
  kind: InquiryKind;
  /**
   * The draft offered by the assistant, or a handoff request restored after a
   * reload; `null` for a new human handoff, which is created on review.
   */
  initialInquiry: InquiryRead | null;
  conversationId: string | null;
  defaults?: Partial<InquiryValues>;
  /** True while the side panel shows this inquiry. */
  active: boolean;
  /** True once the visitor has opened this inquiry in the panel. */
  started: boolean;
  panelBody: HTMLElement | null;
  onOpen: () => void;
}) {
  const { state } = useHealth();
  const simulated = state.status === "ready" && !state.health.providers.crm.live;
  const flow = useInquiryFlow({
    kind: props.kind,
    initialInquiry: props.initialInquiry,
    conversationId: props.conversationId,
    defaults: props.defaults,
  });

  return (
    <>
      <InquiryCard
        flow={flow}
        started={props.started || flow.inquiry !== null}
        simulated={simulated}
        onOpen={props.onOpen}
      />
      {props.active && props.panelBody ? createPortal(<InquiryPanel flow={flow} />, props.panelBody) : null}
    </>
  );
}

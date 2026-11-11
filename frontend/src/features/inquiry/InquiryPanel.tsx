import { CircleAlertIcon, CircleCheckIcon, ClockIcon, RefreshCwIcon } from "lucide-react";
import { useEffect, useId, useRef } from "react";
import type { FormEvent } from "react";

import { Alert, AlertDescription, AlertTitle } from "~/components/ui/alert";
import { Button } from "~/components/ui/button";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import { Spinner } from "~/components/ui/spinner";
import { Textarea } from "~/components/ui/textarea";
import { cn } from "~/lib/utils";

import type { InquiryField, InquiryKind } from "../../api/client";
import { useHealth } from "../../hooks/useHealth";
import type { UiError } from "../../lib/errors";
import { describeDelivery } from "./deliveryStatus";
import type { DeliveryPhase } from "./deliveryStatus";
import { FIELD_LABELS, FIELDS_BY_KIND, MAX_LENGTH, REQUIRED_BY_KIND, valuesFromInquiry } from "./inquiryForm";
import type { InquiryFlow, InquiryStep } from "./useInquiryFlow";

const STEPS: { id: InquiryStep; label: string }[] = [
  { id: "form", label: "Details" },
  { id: "preview", label: "Review" },
  { id: "status", label: "Delivery" },
];

/** Column spans in a six-column grid; fields not listed take the full row. */
const COLUMN_SPAN: Partial<Record<InquiryField, string>> = {
  quantity: "col-span-2",
  timeline: "col-span-4",
  contact_company: "col-span-3",
  contact_phone: "col-span-3",
};

const INPUT_ATTRIBUTES: Partial<Record<InquiryField, { type?: string; inputMode?: "numeric"; autoComplete?: string }>> = {
  quantity: { inputMode: "numeric" },
  contact_name: { autoComplete: "name" },
  contact_email: { type: "email", autoComplete: "email" },
  contact_company: { autoComplete: "organization" },
  contact_phone: { type: "tel", autoComplete: "tel" },
};

const HINTS: Partial<Record<InquiryField, string>> = {
  timeline: "For example: within 4 weeks.",
};

export function inquiryTitle(kind: InquiryKind): string {
  return kind === "handoff" ? "Talk to a person" : "Purchase inquiry";
}

const noun = (kind: InquiryKind) => (kind === "handoff" ? "request" : "inquiry");

function StepList(props: { step: InquiryStep }) {
  const current = STEPS.findIndex((step) => step.id === props.step);
  return (
    <ol className="m-0 flex list-none items-center gap-1.5 p-0 text-xs" aria-label="Steps">
      {STEPS.map((step, index) => (
        <li
          key={step.id}
          aria-current={index === current ? "step" : undefined}
          className={cn(
            "flex items-center gap-1.5",
            index === current ? "font-medium text-foreground" : "text-muted-foreground",
          )}
        >
          {index > 0 ? <span aria-hidden className="h-px w-3 bg-border" /> : null}
          <span className="tabular-nums">{index + 1}</span>
          <span>{step.label}</span>
        </li>
      ))}
    </ol>
  );
}

function RequestError(props: { error: UiError | null }) {
  if (props.error === null) return null;
  return (
    <Alert variant="error" controlAlignment="first-line">
      <CircleAlertIcon aria-hidden />
      <AlertTitle>{props.error.title}</AlertTitle>
      <AlertDescription>{props.error.message}</AlertDescription>
    </Alert>
  );
}

function SimulatedNotice(props: { kind: InquiryKind }) {
  return (
    <Alert variant="warning" controlAlignment="first-line" role="note">
      <CircleAlertIcon aria-hidden />
      <AlertTitle>Delivery is simulated</AlertTitle>
      <AlertDescription>
        Demo mode: no CRM is connected. Confirming creates no CRM record and nobody receives this{" "}
        {noun(props.kind)}.
      </AlertDescription>
    </Alert>
  );
}

function DetailsForm(props: { flow: InquiryFlow; headingId: string }) {
  const { flow } = props;
  const formId = useId();
  const formRef = useRef<HTMLFormElement | null>(null);
  const focusInvalidRef = useRef(false);
  const required = REQUIRED_BY_KIND[flow.kind];

  // After a submit that found problems (here or on the server), go to the first one.
  useEffect(() => {
    if (!focusInvalidRef.current || flow.busy !== null) return;
    focusInvalidRef.current = false;
    formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [flow.errors, flow.busy]);

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    focusInvalidRef.current = true;
    void flow.review();
  };

  return (
    <form
      ref={formRef}
      noValidate
      onSubmit={onSubmit}
      aria-labelledby={props.headingId}
      className="flex flex-col gap-4"
    >
      <div className="grid grid-cols-6 gap-x-3 gap-y-4">
        {FIELDS_BY_KIND[flow.kind].map((field) => {
          const id = `${formId}-${field}`;
          const error = flow.errors[field];
          const hint = HINTS[field];
          const describedBy = [error ? `${id}-error` : null, hint ? `${id}-hint` : null].filter(Boolean).join(" ");
          const common = {
            id,
            name: field,
            value: flow.values[field],
            maxLength: MAX_LENGTH[field],
            "aria-invalid": error ? (true as const) : undefined,
            "aria-required": required.includes(field) ? (true as const) : undefined,
            "aria-describedby": describedBy === "" ? undefined : describedBy,
            disabled: flow.busy !== null,
          };
          return (
            <div
              key={field}
              className={cn("flex min-w-0 flex-col gap-1.5", COLUMN_SPAN[field] ?? "col-span-6")}
            >
              <Label htmlFor={id}>
                {FIELD_LABELS[flow.kind][field]}
                {required.includes(field) ? null : (
                  <span className="font-normal text-muted-foreground">(optional)</span>
                )}
              </Label>
              {field === "notes" ? (
                <Textarea
                  {...common}
                  rows={flow.kind === "handoff" ? 5 : 3}
                  onChange={(event) => flow.setValue(field, event.target.value)}
                />
              ) : (
                <Input
                  {...common}
                  {...INPUT_ATTRIBUTES[field]}
                  onChange={(event) => flow.setValue(field, event.target.value)}
                />
              )}
              {hint ? (
                <p id={`${id}-hint`} className="m-0 text-xs text-muted-foreground">
                  {hint}
                </p>
              ) : null}
              {error ? (
                <p id={`${id}-error`} className="m-0 text-xs text-destructive-foreground">
                  {error}
                </p>
              ) : null}
            </div>
          );
        })}
      </div>
      <RequestError error={flow.error} />
      <div className="flex items-center gap-2">
        <Button type="submit" disabled={flow.busy !== null}>
          {flow.busy === "saving" ? <Spinner aria-hidden /> : null}
          {flow.busy === "saving" ? "Saving" : `Review ${noun(flow.kind)}`}
        </Button>
      </div>
    </form>
  );
}

function SummaryList(props: { flow: InquiryFlow }) {
  const { flow } = props;
  const stored = valuesFromInquiry(flow.inquiry);
  const rows = FIELDS_BY_KIND[flow.kind].filter((field) => stored[field].trim() !== "");
  return (
    <dl className="m-0 flex flex-col rounded-xl border border-border/60 bg-card/50 px-3">
      {rows.map((field) => (
        <div key={field} className="flex gap-3 border-b border-border/60 py-2 text-sm last:border-b-0">
          <dt className="w-[4.5rem] shrink-0 text-muted-foreground">{FIELD_LABELS[flow.kind][field]}</dt>
          <dd className="m-0 min-w-0 flex-1 whitespace-pre-wrap text-foreground [overflow-wrap:anywhere]">
            {stored[field]}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Preview(props: { flow: InquiryFlow }) {
  const { flow } = props;
  const { state } = useHealth();
  const simulated = state.status === "ready" && !state.health.providers.crm.live;
  return (
    <div className="flex flex-col gap-4">
      <SummaryList flow={flow} />
      {simulated ? <SimulatedNotice kind={flow.kind} /> : null}
      <RequestError error={flow.error} />
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => void flow.confirm()} disabled={flow.busy !== null}>
          {flow.busy === "confirming" ? <Spinner aria-hidden /> : null}
          {flow.busy === "confirming" ? "Sending" : "Confirm and send"}
        </Button>
        <Button variant="outline" onClick={flow.edit} disabled={flow.busy !== null}>
          Edit details
        </Button>
      </div>
    </div>
  );
}

const PHASE_STYLE: Record<DeliveryPhase, string> = {
  queued: "text-info",
  sending: "text-info",
  retrying: "text-warning",
  delivered: "text-success",
  failed: "text-destructive",
};

function PhaseIcon(props: { phase: DeliveryPhase }) {
  const className = cn("size-4 shrink-0", PHASE_STYLE[props.phase]);
  switch (props.phase) {
    case "queued":
      return <ClockIcon aria-hidden className={className} />;
    case "sending":
      return <Spinner aria-hidden className={className} />;
    case "retrying":
      return <RefreshCwIcon aria-hidden className={className} />;
    case "delivered":
      return <CircleCheckIcon aria-hidden className={className} />;
    case "failed":
      return <CircleAlertIcon aria-hidden className={className} />;
  }
}

function DeliveryStatusView(props: { flow: InquiryFlow }) {
  const { flow } = props;
  const view = describeDelivery(flow.delivery, flow.kind);
  const attempts = flow.delivery?.attempt_count ?? 0;
  // A simulated delivery that "arrived" is still not a delivery: no success color.
  const simulatedDone = view.phase === "delivered" && flow.delivery !== null && !flow.delivery.live;

  return (
    <div className="flex flex-col gap-4">
      <div
        role="status"
        aria-live="polite"
        className="flex items-start gap-2.5 rounded-xl border border-border/60 bg-card/50 p-3"
      >
        <span className={cn("mt-0.5 flex", simulatedDone && "[&_svg]:text-warning")}>
          <PhaseIcon phase={view.phase} />
        </span>
        <div className="flex min-w-0 flex-col gap-0.5">
          <p className="m-0 text-sm font-medium text-foreground">{view.label}</p>
          <p className="m-0 text-sm leading-relaxed text-muted-foreground">{view.detail}</p>
          {attempts > 0 ? (
            <p className="m-0 text-xs text-muted-foreground tabular-nums">
              {attempts === 1 ? "1 attempt" : `${attempts} attempts`}
            </p>
          ) : null}
        </div>
      </div>

      {flow.statusStale ? (
        <p className="m-0 text-xs text-muted-foreground" role="status">
          Cannot refresh the status right now. Trying again.
        </p>
      ) : null}

      <RequestError error={flow.error} />

      {view.phase === "failed" ? (
        <div>
          <Button onClick={() => void flow.retryDelivery()} disabled={flow.busy !== null}>
            {flow.busy === "retrying" ? <Spinner aria-hidden /> : <RefreshCwIcon aria-hidden />}
            {flow.busy === "retrying" ? "Sending again" : "Send again"}
          </Button>
        </div>
      ) : null}

      <div className="flex flex-col gap-1.5">
        <h3 className="m-0 text-xs font-medium text-muted-foreground">What you sent</h3>
        <SummaryList flow={flow} />
      </div>
    </div>
  );
}

const STEP_HEADING: Record<InquiryStep, (kind: InquiryKind) => string> = {
  form: inquiryTitle,
  preview: (kind) => `Review your ${noun(kind)}`,
  status: () => "Delivery status",
};

const STEP_INTRO: Record<InquiryStep, (kind: InquiryKind) => string> = {
  form: (kind) =>
    kind === "handoff"
      ? "Send your question to the Northline team. You review it before it is sent."
      : "Tell us what you need. You review the inquiry before it is sent.",
  preview: () => "Nothing is sent until you confirm.",
  status: (kind) => `Your ${noun(kind)} is confirmed. This page follows its delivery.`,
};

/** The inquiry path in the side panel: details, review with explicit confirmation, delivery status. */
export function InquiryPanel(props: { flow: InquiryFlow }) {
  const { flow } = props;
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const shownStepRef = useRef(flow.step);

  // Moving to another step replaces the content, so focus follows to its heading.
  useEffect(() => {
    if (shownStepRef.current === flow.step) return;
    shownStepRef.current = flow.step;
    headingRef.current?.focus();
  }, [flow.step]);

  return (
    <section className="flex flex-col gap-4 px-4 pb-6 pt-1 sm:px-5" aria-labelledby={headingId}>
      <StepList step={flow.step} />
      <div className="flex flex-col gap-1">
        <h2
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="m-0 text-base font-medium text-foreground outline-none"
        >
          {STEP_HEADING[flow.step](flow.kind)}
        </h2>
        <p className="m-0 text-sm leading-relaxed text-muted-foreground">{STEP_INTRO[flow.step](flow.kind)}</p>
      </div>
      {flow.step === "form" ? <DetailsForm flow={flow} headingId={headingId} /> : null}
      {flow.step === "preview" ? <Preview flow={flow} /> : null}
      {flow.step === "status" ? <DeliveryStatusView flow={flow} /> : null}
    </section>
  );
}

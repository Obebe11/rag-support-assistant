import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError, unwrap } from "../../api/client";
import type { DeliveryRead, InquiryField, InquiryKind, InquiryRead } from "../../api/client";
import { describeError } from "../../lib/errors";
import type { UiError } from "../../lib/errors";
import { timing } from "../../lib/timing";
import {
  errorsFromDetails,
  errorsFromMissingFields,
  FIELDS_BY_KIND,
  toCreateBody,
  toUpdateBody,
  validateInquiry,
  valuesFromInquiry,
} from "./inquiryForm";
import type { InquiryErrors, InquiryValues } from "./inquiryForm";

export type InquiryStep = "form" | "preview" | "status";
export type InquiryBusy = "saving" | "confirming" | "retrying" | null;

export interface InquiryFlowOptions {
  kind: InquiryKind;
  /** The draft offered by the assistant, or `null` to create one on review. */
  initialInquiry: InquiryRead | null;
  conversationId: string | null;
  /** Values for fields the draft leaves empty, for example the visitor's question. */
  defaults?: Partial<InquiryValues>;
  pollIntervalMs?: number;
}

export interface InquiryFlow {
  kind: InquiryKind;
  step: InquiryStep;
  values: InquiryValues;
  errors: InquiryErrors;
  /** A failed request; field problems are in `errors`. */
  error: UiError | null;
  busy: InquiryBusy;
  /** The inquiry as the server stored it; the preview shows this, not the form values. */
  inquiry: InquiryRead | null;
  delivery: DeliveryRead | null;
  /** True while the delivery status cannot be refreshed. The last known status stays visible. */
  statusStale: boolean;
  setValue: (field: InquiryField, value: string) => void;
  review: () => Promise<void>;
  edit: () => void;
  confirm: () => Promise<void>;
  retryDelivery: () => Promise<void>;
}

function isActive(delivery: DeliveryRead | null): boolean {
  return delivery === null || delivery.status === "pending" || delivery.status === "in_progress";
}

/**
 * One inquiry from draft to delivery: edit, save and review, confirm once,
 * then follow the delivery status until it is delivered or failed.
 *
 * A handoff (`kind: "handoff"`) follows the same path with fewer fields.
 */
export function useInquiryFlow(options: InquiryFlowOptions): InquiryFlow {
  const { kind, conversationId, pollIntervalMs = timing.deliveryPollMs } = options;
  const [inquiry, setInquiry] = useState<InquiryRead | null>(options.initialInquiry);
  const [step, setStep] = useState<InquiryStep>(
    options.initialInquiry?.status === "confirmed" ? "status" : "form",
  );
  const [values, setValues] = useState<InquiryValues>(() =>
    valuesFromInquiry(options.initialInquiry, options.defaults),
  );
  const [errors, setErrors] = useState<InquiryErrors>({});
  const [error, setError] = useState<UiError | null>(null);
  const [busy, setBusy] = useState<InquiryBusy>(null);
  const [delivery, setDelivery] = useState<DeliveryRead | null>(options.initialInquiry?.delivery ?? null);
  const [statusStale, setStatusStale] = useState(false);
  /** Set synchronously, so a double click cannot start a second request before React re-renders. */
  const lockRef = useRef(false);

  const inquiryId = inquiry?.id ?? null;
  const polling = step === "status" && inquiryId !== null && isActive(delivery);

  useEffect(() => {
    if (!polling || inquiryId === null) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const next = await unwrap(
          api.GET("/api/inquiries/{inquiry_id}/delivery", { params: { path: { inquiry_id: inquiryId } } }),
        );
        if (cancelled) return;
        setStatusStale(false);
        setDelivery(next);
        if (isActive(next)) timer = setTimeout(tick, pollIntervalMs);
      } catch {
        if (cancelled) return;
        setStatusStale(true);
        timer = setTimeout(tick, pollIntervalMs);
      }
    };
    timer = setTimeout(tick, pollIntervalMs);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [polling, inquiryId, pollIntervalMs]);

  const setValue = useCallback((field: InquiryField, value: string) => {
    setValues((current) => ({ ...current, [field]: value }));
    setErrors((current) => {
      if (!(field in current)) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  }, []);

  const showStatus = useCallback((confirmed: InquiryRead) => {
    setInquiry(confirmed);
    setDelivery(confirmed.delivery ?? null);
    setErrors({});
    setError(null);
    setStep("status");
  }, []);

  /** After a 409: read the inquiry again and show the state the server is in. */
  const resync = useCallback(
    async (id: string): Promise<boolean> => {
      try {
        const current = await unwrap(api.GET("/api/inquiries/{inquiry_id}", { params: { path: { inquiry_id: id } } }));
        if (current.status === "confirmed") {
          showStatus(current);
          return true;
        }
        setInquiry(current);
        const missing = (current.missing_fields ?? []).filter((field) => FIELDS_BY_KIND[kind].includes(field));
        if (missing.length > 0) {
          setErrors(errorsFromMissingFields(kind, missing));
          setStep("form");
          return true;
        }
      } catch {
        // Fall through: the caller reports the original error.
      }
      return false;
    },
    [kind, showStatus],
  );

  const review = useCallback(async () => {
    if (lockRef.current) return;
    const problems = validateInquiry(kind, values);
    setErrors(problems);
    setError(null);
    if (Object.keys(problems).length > 0) return;

    lockRef.current = true;
    setBusy("saving");
    try {
      const saved =
        inquiryId === null
          ? await unwrap(api.POST("/api/inquiries", { body: toCreateBody(kind, values, conversationId) }))
          : await unwrap(
              api.PATCH("/api/inquiries/{inquiry_id}", {
                params: { path: { inquiry_id: inquiryId } },
                body: toUpdateBody(kind, values),
              }),
            );
      setInquiry(saved);
      const missing = saved.missing_fields ?? [];
      const visibleMissing = missing.filter((field) => FIELDS_BY_KIND[kind].includes(field));
      if (visibleMissing.length > 0) {
        setErrors(errorsFromMissingFields(kind, visibleMissing));
      } else if (missing.length > 0) {
        setError({
          kind: "request",
          title: "The inquiry is incomplete",
          message: "The server needs more details than this form collects. Ask in the chat instead.",
          status: 0,
        });
      } else {
        setStep("preview");
      }
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409 && inquiryId !== null) {
        if (await resync(inquiryId)) return;
      }
      if (caught instanceof ApiError && caught.status === 422) {
        const fieldErrors = errorsFromDetails(caught.details);
        if (Object.keys(fieldErrors).length > 0) {
          setErrors(fieldErrors);
          return;
        }
      }
      setError(describeError(caught));
    } finally {
      lockRef.current = false;
      setBusy(null);
    }
  }, [conversationId, inquiryId, kind, resync, values]);

  const edit = useCallback(() => {
    if (lockRef.current) return;
    setError(null);
    setStep("form");
  }, []);

  const confirm = useCallback(async () => {
    if (lockRef.current || inquiryId === null) return;
    lockRef.current = true;
    setBusy("confirming");
    setError(null);
    try {
      const confirmed = await unwrap(
        api.POST("/api/inquiries/{inquiry_id}/confirm", { params: { path: { inquiry_id: inquiryId } } }),
      );
      showStatus(confirmed);
    } catch (caught) {
      // 422: a required field is still empty; the details name the fields.
      if (caught instanceof ApiError && caught.status === 422) {
        const missing = Object.keys(errorsFromDetails(caught.details)) as InquiryField[];
        const visible = missing.filter((field) => FIELDS_BY_KIND[kind].includes(field));
        if (visible.length > 0) {
          setErrors(errorsFromMissingFields(kind, visible));
          setStep("form");
          return;
        }
      }
      // 409: the server holds another state of this inquiry; show that state.
      if (caught instanceof ApiError && caught.status === 409 && (await resync(inquiryId))) return;
      setError(describeError(caught));
    } finally {
      lockRef.current = false;
      setBusy(null);
    }
  }, [inquiryId, kind, resync, showStatus]);

  const retryDelivery = useCallback(async () => {
    if (lockRef.current || inquiryId === null) return;
    lockRef.current = true;
    setBusy("retrying");
    setError(null);
    try {
      const next = await unwrap(
        api.POST("/api/inquiries/{inquiry_id}/delivery/retry", { params: { path: { inquiry_id: inquiryId } } }),
      );
      setStatusStale(false);
      setDelivery(next);
    } catch (caught) {
      // 409: the delivery is no longer failed, so show its current state.
      if (caught instanceof ApiError && caught.status === 409 && (await resync(inquiryId))) return;
      setError(describeError(caught));
    } finally {
      lockRef.current = false;
      setBusy(null);
    }
  }, [inquiryId, resync]);

  return {
    kind,
    step,
    values,
    errors,
    error,
    busy,
    inquiry,
    delivery,
    statusStale,
    setValue,
    review,
    edit,
    confirm,
    retryDelivery,
  };
}

/*
 * Adapted from T3 Code (apps/web/src/components/ChatView.tsx,
 * chat/ChatComposer.tsx, ComposerPromptEditor.tsx and
 * chat/ComposerPrimaryActions.tsx, MIT, (c) 2026 T3 Tools Inc.). RAG Support Assistant
 * keeps the docked and centered ("draft hero") overlay, the glass shell, the
 * padding rows, the footer and the round send button. The Lexical editor is
 * replaced by a textarea with the editor's classes; model, mode and attachment
 * controls, banners, drawers and the collapsed mobile composer are not ported.
 */
import type { ComponentPropsWithoutRef, FormEventHandler, ReactNode, Ref } from "react";

import { Spinner } from "~/components/ui/spinner";
import { cn } from "~/lib/utils";

export function ComposerDock({
  hero,
  headline,
  below,
  dockRef,
  children,
}: {
  /** Centered with a headline above it, before the first message. */
  hero: boolean;
  headline?: ReactNode;
  /** Shown under the composer in the hero state. */
  below?: ReactNode;
  dockRef?: Ref<HTMLDivElement>;
  children: ReactNode;
}) {
  return (
    <div
      ref={dockRef}
      data-chat-composer-overlay="true"
      className={
        hero
          ? "pointer-events-none absolute inset-0 z-20 flex items-center"
          : "pointer-events-none absolute inset-x-0 bottom-0 z-20 pt-1.5 sm:pt-2"
      }
    >
      <div className="w-full ps-[calc(env(safe-area-inset-left)+0.75rem)] pe-[calc(env(safe-area-inset-right)+0.75rem)] sm:ps-[calc(env(safe-area-inset-left)+1.25rem)] sm:pe-[calc(env(safe-area-inset-right)+1.25rem)]">
        <div className="pointer-events-auto relative z-10">
          {hero && headline ? (
            <div className="absolute inset-x-0 bottom-full z-0">
              <div className="pb-8">{headline}</div>
            </div>
          ) : null}
          <div className="relative">
            <div className="chat-composer-glass-shell relative mx-auto w-full max-w-3xl">
              <div className="chat-composer-glass-host relative z-10 w-full rounded-[22px]">
                <div className="relative z-10">{children}</div>
              </div>
            </div>
            {hero ? (
              below ? (
                <div className="absolute inset-x-0 top-full z-0 pt-4">{below}</div>
              ) : null
            ) : (
              <div
                aria-hidden
                className="h-[calc(env(safe-area-inset-bottom)+1rem)] sm:h-[calc(env(safe-area-inset-bottom)+1.25rem)]"
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function ComposerForm(props: {
  onSubmit: FormEventHandler<HTMLFormElement>;
  label: string;
  editor: ReactNode;
  footerStart?: ReactNode;
  footerEnd: ReactNode;
}) {
  return (
    <form
      className="mx-auto w-full min-w-0 max-w-3xl"
      data-chat-composer-form="true"
      aria-label={props.label}
      onSubmit={props.onSubmit}
    >
      <div className="group relative z-10 rounded-[22px] p-px transition-colors duration-200">
        <div className="rounded-[20px] transition-[background-color] duration-200">
          <div className="relative px-3 pb-2 pt-3.5 sm:px-4 sm:pt-4">
            <div className="relative [font-size:0.875rem] [@media(max-width:39.999rem)_and_(pointer:coarse)]:[font-size:16px]">
              {props.editor}
            </div>
          </div>
          <div
            data-chat-composer-footer="true"
            className="flex min-w-0 flex-nowrap items-center justify-between gap-2 overflow-visible px-3 pb-3 sm:px-4 sm:pb-4"
          >
            <div className="flex min-w-0 flex-1 items-center gap-1">{props.footerStart}</div>
            <div
              data-chat-composer-actions="right"
              className="flex shrink-0 flex-nowrap items-center justify-end gap-2"
            >
              {props.footerEnd}
            </div>
          </div>
        </div>
      </div>
    </form>
  );
}

/** A textarea with the classes of T3 Code's prompt editor. */
export function ComposerTextarea({
  className,
  textareaRef,
  ...props
}: ComponentPropsWithoutRef<"textarea"> & { textareaRef?: Ref<HTMLTextAreaElement> }) {
  return (
    <textarea
      ref={textareaRef}
      rows={2}
      className={cn(
        "block field-sizing-content max-h-50 min-h-17.5 w-full resize-none overflow-y-auto whitespace-pre-wrap wrap-break-word bg-transparent leading-relaxed text-foreground placeholder:text-placeholder focus:outline-none",
        className,
      )}
      data-testid="composer-editor"
      {...props}
    />
  );
}

export function ComposerSendButton(props: { busy: boolean; disabled: boolean; label: string }) {
  return (
    <button
      type="submit"
      className="relative isolate flex h-9 w-9 items-center justify-center overflow-hidden rounded-full bg-message-action text-message-action-foreground shadow-xs transition-all duration-150 enabled:cursor-pointer enabled:inset-shadow-[0_1px_--theme(--color-white/16%)] enabled:shadow-message-action/24 hover:scale-105 hover:bg-message-action-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring active:inset-shadow-[0_1px_--theme(--color-black/8%)] active:shadow-none disabled:pointer-events-none disabled:opacity-30 disabled:shadow-none disabled:hover:scale-100 sm:h-8 sm:w-8"
      disabled={props.disabled || props.busy}
      aria-label={props.label}
    >
      {props.busy ? (
        <Spinner className="size-3.5" aria-hidden="true" />
      ) : (
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <path
            d="M7 11.5V2.5M7 2.5L3 6.5M7 2.5L11 6.5"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </button>
  );
}

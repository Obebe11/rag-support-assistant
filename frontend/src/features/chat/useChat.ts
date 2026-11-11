import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError, unwrap } from "../../api/client";
import type { MessageRead } from "../../api/client";
import { describeError } from "../../lib/errors";
import type { UiError } from "../../lib/errors";

/** A visitor message that the server has not stored yet. */
export interface PendingMessage {
  localId: string;
  content: string;
  status: "sending" | "failed";
  error: UiError | null;
}

export type ChatPhase =
  /** Loading the conversation of this browser tab after a page reload. */
  | "restoring"
  | "restore_failed"
  | "ready";

export interface ChatState {
  phase: ChatPhase;
  messages: MessageRead[];
  /** At most one message is in flight; a failed one waits for retry or removal. */
  pending: PendingMessage | null;
  /**
   * The assistant message received in this page view, or `null` after a reload
   * or a new conversation. Tells a new reply from restored history.
   */
  latestReplyId: string | null;
  /** Grows with every "new conversation", so views can reset their own state. */
  generation: number;
}

export interface Chat extends ChatState {
  conversationId: string | null;
  isSending: boolean;
  send: (content: string) => void;
  retry: () => void;
  discardFailed: () => void;
  retryRestore: () => void;
  startNew: () => void;
}

const STORAGE_KEY = "handoff-ai:conversation-id";

/** The conversation id lives for the browser tab; it is not a secret or a login. */
const storedConversation = {
  read(): string | null {
    try {
      return window.sessionStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  },
  write(id: string | null): void {
    try {
      if (id === null) window.sessionStorage.removeItem(STORAGE_KEY);
      else window.sessionStorage.setItem(STORAGE_KEY, id);
    } catch {
      // Storage can be unavailable (private mode); the chat still works for this page view.
    }
  },
};

let localIdCounter = 0;

/**
 * Chat state for one conversation: history, sending with retry, and restoring
 * the conversation after a reload. The conversation is created on the first
 * message, so opening the page creates nothing on the server.
 */
export function useChat(): Chat {
  const [conversationId, setConversationId] = useState<string | null>(() => storedConversation.read());
  const [state, setState] = useState<ChatState>(() => ({
    phase: storedConversation.read() === null ? "ready" : "restoring",
    messages: [],
    pending: null,
    latestReplyId: null,
    generation: 0,
  }));
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const conversationIdRef = useRef(conversationId);
  const sendingRef = useRef(false);
  /** Bumped by "new conversation", so a late reply to the old one is dropped. */
  const generationRef = useRef(0);

  useEffect(() => {
    const id = conversationIdRef.current;
    if (id === null) return;
    let active = true;
    unwrap(api.GET("/api/conversations/{conversation_id}", { params: { path: { conversation_id: id } } })).then(
      (conversation) => {
        if (!active) return;
        setState((current) => ({ ...current, phase: "ready", messages: conversation.messages ?? [] }));
      },
      (error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
          // The conversation no longer exists: start a new one without an error.
          storedConversation.write(null);
          conversationIdRef.current = null;
          setConversationId(null);
          setState((current) => ({ ...current, phase: "ready", messages: [], pending: null, latestReplyId: null }));
        } else {
          setState((current) => ({ ...current, phase: "restore_failed" }));
        }
      },
    );
    return () => {
      active = false;
    };
    // Runs on mount and on an explicit retry; the id is read from the ref on purpose.
  }, [restoreAttempt]);

  const deliver = useCallback(async (pending: PendingMessage) => {
    if (sendingRef.current) return;
    sendingRef.current = true;
    const generation = generationRef.current;
    setState((current) => ({ ...current, pending: { ...pending, status: "sending", error: null } }));
    try {
      let id = conversationIdRef.current;
      if (id === null) {
        const conversation = await unwrap(api.POST("/api/conversations"));
        if (generation !== generationRef.current) return;
        id = conversation.id;
        conversationIdRef.current = id;
        storedConversation.write(id);
        setConversationId(id);
      }
      const exchange = await unwrap(
        api.POST("/api/conversations/{conversation_id}/messages", {
          params: { path: { conversation_id: id } },
          body: { content: pending.content },
        }),
      );
      if (generation !== generationRef.current) return;
      setState((current) => ({
        ...current,
        messages: [...current.messages, exchange.user_message, exchange.assistant_message],
        pending: null,
        latestReplyId: exchange.assistant_message.id,
      }));
    } catch (error) {
      if (generation !== generationRef.current) return;
      setState((current) => ({
        ...current,
        pending: { ...pending, status: "failed", error: describeError(error) },
      }));
    } finally {
      // After "new conversation" the lock belongs to the new generation.
      if (generation === generationRef.current) sendingRef.current = false;
    }
  }, []);

  const send = useCallback(
    (content: string) => {
      const trimmed = content.trim();
      if (trimmed === "" || sendingRef.current) return;
      localIdCounter += 1;
      void deliver({ localId: `local-${localIdCounter}`, content: trimmed, status: "sending", error: null });
    },
    [deliver],
  );

  const pendingRef = useRef(state.pending);
  useEffect(() => {
    pendingRef.current = state.pending;
  }, [state.pending]);

  const retry = useCallback(() => {
    const pending = pendingRef.current;
    if (pending?.status === "failed") void deliver(pending);
  }, [deliver]);

  const discardFailed = useCallback(() => {
    setState((current) => (current.pending?.status === "failed" ? { ...current, pending: null } : current));
  }, []);

  const retryRestore = useCallback(() => {
    setState((current) => ({ ...current, phase: "restoring" }));
    setRestoreAttempt((attempt) => attempt + 1);
  }, []);

  const startNew = useCallback(() => {
    generationRef.current += 1;
    sendingRef.current = false;
    conversationIdRef.current = null;
    storedConversation.write(null);
    setConversationId(null);
    setState((current) => ({
      phase: "ready",
      messages: [],
      pending: null,
      latestReplyId: null,
      generation: current.generation + 1,
    }));
  }, []);

  return {
    ...state,
    conversationId,
    isSending: state.pending?.status === "sending",
    send,
    retry,
    discardFailed,
    retryRestore,
    startNew,
  };
}

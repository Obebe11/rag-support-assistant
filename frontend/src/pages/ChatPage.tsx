import { CircleAlertIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";

import { ChatMarkdown } from "~/components/chat/ChatMarkdown";
import { ComposerDock, ComposerForm, ComposerSendButton, ComposerTextarea } from "~/components/chat/Composer";
import {
  AssistantMessage,
  DraftHeroHeadline,
  TimelineRow,
  TimelineViewport,
  UserMessage,
  WorkingRow,
} from "~/components/chat/Timeline";
import { RightPanel, RightPanelControls, RightPanelToggle, useRightPanelSheetMode } from "~/components/RightPanel";
import type { RightPanelTab } from "~/components/RightPanel";
import { Alert, AlertDescription, AlertTitle } from "~/components/ui/alert";
import { Button } from "~/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "~/components/ui/empty";
import { Skeleton } from "~/components/ui/skeleton";

import type { InquiryKind, MessageRead } from "../api/client";
import { HealthBanner } from "../app/HealthBanner";
import { PageHeader } from "../app/PageHeader";
import { useChatContext } from "../features/chat/ChatProvider";
import { SourcesList } from "../features/chat/SourcesList";
import { SourcesPanel } from "../features/chat/SourcesPanel";
import type { Chat } from "../features/chat/useChat";
import { InquiryThread } from "../features/inquiry/InquiryThread";
import { restoredHandoffs } from "../features/inquiry/restoredHandoffs";

// Questions the demo knowledge base answers in every mode, including the keyless local one.
const EXAMPLE_QUESTIONS = [
  "How much does shipping cost?",
  "How long do I have to return an item?",
  "What does the warranty cover?",
];

const MESSAGE_MAX_LENGTH = 4000;

type PanelTab = "sources" | "inquiry";

interface PanelState {
  open: boolean;
  tab: PanelTab;
  /** The answer whose sources are shown; `null` means the latest grounded answer. */
  sourcesMessageId: string | null;
  citationIndex: number | null;
  /** The inquiry shown in the "inquiry" tab, by the id of its message. */
  flow: { key: string; kind: InquiryKind } | null;
  /** The visitor closed the panel, so new replies no longer open it. */
  userClosed: boolean;
}

const CLOSED_PANEL: PanelState = {
  open: false,
  tab: "sources",
  sourcesMessageId: null,
  citationIndex: null,
  flow: null,
  userClosed: false,
};

/** Reply types that can carry sources. A refusal and an unknown type never show them. */
const CITING_TYPES = new Set<MessageRead["answer_type"]>([
  "grounded",
  "inquiry_offer",
  "clarification",
  "knowledge_gap",
]);

/**
 * A grounded answer has sources. So does an inquiry offer whose message also
 * asked a question: the reply answers it first and then offers the inquiry.
 * A clarifying question or a knowledge gap has them when it names documented
 * facts, such as the options to choose from.
 */
function hasSources(message: MessageRead): boolean {
  return CITING_TYPES.has(message.answer_type) && (message.citations?.length ?? 0) > 0;
}

/**
 * What a new reply does to the side panel. Beside the chat (wide windows) the
 * panel opens for sources and for an offered inquiry; as a sheet it would
 * cover the answer, so there it opens only when the visitor asks for it.
 */
function panelAfterReply(panel: PanelState, reply: MessageRead, sheetMode: boolean): PanelState {
  const mayOpen = !sheetMode && !panel.userClosed;
  let next = panel;
  if (hasSources(reply)) {
    next = { ...next, sourcesMessageId: reply.id, citationIndex: null };
    if (mayOpen) {
      // Do not pull the visitor out of an inquiry they have open.
      const inInquiry = panel.open && panel.tab === "inquiry" && panel.flow !== null;
      next = { ...next, open: true, tab: inInquiry ? "inquiry" : "sources" };
    }
  }
  if (reply.answer_type === "inquiry_offer" && reply.inquiry) {
    next = { ...next, flow: { key: reply.id, kind: reply.inquiry.kind } };
    if (mayOpen) next = { ...next, open: true, tab: "inquiry" };
  }
  return next;
}

function RestoringRows() {
  return (
    <div aria-busy="true" aria-label="Loading the conversation">
      <TimelineRow>
        <div className="flex justify-end">
          <Skeleton className="h-10 w-56 max-w-[70%] rounded-2xl" />
        </div>
      </TimelineRow>
      <TimelineRow>
        <div className="flex flex-col gap-2 px-1">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      </TimelineRow>
    </div>
  );
}

function ChatView({ chat }: { chat: Chat }) {
  const sheetMode = useRightPanelSheetMode();
  const [panel, setPanel] = useState<PanelState>(CLOSED_PANEL);
  const [panelBody, setPanelBody] = useState<HTMLDivElement | null>(null);
  const [startedFlows, setStartedFlows] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [dockHeight, setDockHeight] = useState(0);
  const dockRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const focusPanelRef = useRef(false);

  const { messages, pending, phase } = chat;
  const hero = phase === "ready" && messages.length === 0 && pending === null;

  // A reply that arrived in this page view may open the panel; restored history does not.
  const [handledReplyId, setHandledReplyId] = useState<string | null>(null);
  if (chat.latestReplyId !== handledReplyId) {
    setHandledReplyId(chat.latestReplyId);
    const reply = messages.find((message) => message.id === chat.latestReplyId);
    if (reply) setPanel((current) => panelAfterReply(current, reply, sheetMode));
  }

  useEffect(() => {
    const dock = dockRef.current;
    if (!dock || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setDockHeight(dock.offsetHeight));
    observer.observe(dock);
    return () => observer.disconnect();
  }, [hero]);

  // Keep the newest message in view.
  const messageCount = messages.length;
  const pendingStatus = pending?.status ?? null;
  useEffect(() => {
    const viewport = scrollRef.current;
    if (viewport) viewport.scrollTop = viewport.scrollHeight;
  }, [messageCount, pendingStatus, dockHeight]);

  // Stay at the bottom while the newest card grows: a draft becomes a review, a delivery
  // status changes. A visitor who scrolled up to read is left where they are.
  useEffect(() => {
    const viewport = scrollRef.current;
    if (!viewport || typeof MutationObserver === "undefined") return;
    let pinned = true;
    const onScroll = () => {
      pinned = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 48;
    };
    const observer = new MutationObserver(() => {
      if (pinned) viewport.scrollTop = viewport.scrollHeight;
    });
    viewport.addEventListener("scroll", onScroll, { passive: true });
    observer.observe(viewport, { childList: true, subtree: true, characterData: true });
    return () => {
      viewport.removeEventListener("scroll", onScroll);
      observer.disconnect();
    };
  }, []);

  // A panel opened by the visitor takes focus; one opened by a new reply does not.
  useEffect(() => {
    if (!focusPanelRef.current || panelBody === null || !panel.open) return;
    focusPanelRef.current = false;
    if (!sheetMode) panelBody.focus();
  }, [panel, panelBody, sheetMode]);

  /** The live card of an inquiry is on the latest message that carries it. */
  const latestOfferMessage = useMemo(() => {
    const byInquiry = new Map<string, string>();
    for (const message of messages) {
      if (message.answer_type === "inquiry_offer" && message.inquiry) {
        byInquiry.set(message.inquiry.id, message.id);
      }
    }
    return byInquiry;
  }, [messages]);

  /** Handoff requests made before a reload, by the knowledge-gap message they belong to. */
  const handoffs = useMemo(
    () => restoredHandoffs(messages, chat.restoredInquiries),
    [messages, chat.restoredInquiries],
  );

  const sourcesMessage =
    messages.find((message) => message.id === panel.sourcesMessageId) ??
    [...messages].reverse().find(hasSources) ??
    null;
  const citations = sourcesMessage?.citations ?? [];

  const tabs: RightPanelTab[] = [{ id: "sources", title: "Sources" }];
  if (panel.flow) {
    tabs.push({ id: "inquiry", title: panel.flow.kind === "handoff" ? "Talk to a person" : "Inquiry" });
  }
  const activeTab: PanelTab = panel.tab === "inquiry" && panel.flow ? "inquiry" : "sources";

  const openSources = useCallback((messageId: string, index: number) => {
    focusPanelRef.current = true;
    setPanel((current) => ({
      ...current,
      open: true,
      tab: "sources",
      sourcesMessageId: messageId,
      citationIndex: index,
      userClosed: false,
    }));
  }, []);

  const openFlow = useCallback((key: string, kind: InquiryKind) => {
    focusPanelRef.current = true;
    setStartedFlows((current) => (current.includes(key) ? current : [...current, key]));
    setPanel((current) => ({ ...current, open: true, tab: "inquiry", flow: { key, kind }, userClosed: false }));
  }, []);

  const closePanel = useCallback(() => {
    setPanel((current) => ({ ...current, open: false, userClosed: true }));
  }, []);

  const togglePanel = useCallback(() => {
    setPanel((current) =>
      current.open ? { ...current, open: false, userClosed: true } : { ...current, open: true, userClosed: false },
    );
  }, []);

  const canSend = phase === "ready" && pending === null && draft.trim() !== "";

  const submit = (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    if (!canSend) return;
    chat.send(draft);
    setDraft("");
  };

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  const askExample = (question: string) => {
    if (phase !== "ready" || pending !== null) return;
    chat.send(question);
    textareaRef.current?.focus();
  };

  const toggle = (
    <RightPanelToggle
      open={panel.open}
      onToggle={togglePanel}
      label={panel.open ? "Close side panel" : "Open side panel"}
    />
  );
  const panelBesideChat = panel.open && !sheetMode;

  return (
    <div className="relative flex min-h-0 min-w-0 flex-1 overflow-hidden bg-background">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-x-hidden">
        <PageHeader title="Support chat" reserveToggleSpace={!panelBesideChat} />
        <div className="relative flex min-h-0 flex-1 flex-col">
          <HealthBanner />
          <TimelineViewport scrollRef={scrollRef} bottomInset={hero ? 0 : dockHeight} label="Conversation">
            {phase === "restoring" ? <RestoringRows /> : null}
            {phase === "restore_failed" ? (
              <Empty className="py-16">
                <EmptyHeader>
                  <EmptyTitle className="text-base font-medium">The conversation did not load</EmptyTitle>
                  <EmptyDescription>
                    The server did not return your earlier messages. Try again, or start a new conversation.
                  </EmptyDescription>
                </EmptyHeader>
                <EmptyContent className="flex-row justify-center gap-2">
                  <Button onClick={chat.retryRestore}>Try again</Button>
                  <Button variant="outline" onClick={chat.startNew}>
                    New conversation
                  </Button>
                </EmptyContent>
              </Empty>
            ) : null}

            {messages.map((message, index) => {
              if (message.role === "user") {
                return (
                  <TimelineRow key={message.id} data-message-role="user">
                    <UserMessage>{message.content}</UserMessage>
                  </TimelineRow>
                );
              }
              const question = messages
                .slice(0, index)
                .reverse()
                .find((earlier) => earlier.role === "user")?.content;
              const offer = message.answer_type === "inquiry_offer" ? (message.inquiry ?? null) : null;
              const superseded = offer !== null && latestOfferMessage.get(offer.id) !== message.id;
              return (
                <TimelineRow key={message.id} data-message-role="assistant">
                  <AssistantMessage>
                    <ChatMarkdown text={message.content} />
                    {hasSources(message) ? (
                      <SourcesList
                        citations={message.citations ?? []}
                        shownInPanel={panelBesideChat && activeTab === "sources" && sourcesMessage?.id === message.id}
                        onOpen={(citationIndex) => openSources(message.id, citationIndex)}
                      />
                    ) : null}
                    {message.answer_type === "knowledge_gap" ? (
                      <InquiryThread
                        kind="handoff"
                        initialInquiry={handoffs.get(message.id) ?? null}
                        conversationId={chat.conversationId}
                        defaults={{ notes: question ?? "" }}
                        active={panel.open && activeTab === "inquiry" && panel.flow?.key === message.id}
                        started={startedFlows.includes(message.id) || handoffs.has(message.id)}
                        panelBody={panelBody}
                        onOpen={() => openFlow(message.id, "handoff")}
                      />
                    ) : null}
                    {offer !== null && !superseded ? (
                      <InquiryThread
                        kind={offer.kind}
                        initialInquiry={offer}
                        conversationId={chat.conversationId}
                        active={panel.open && activeTab === "inquiry" && panel.flow?.key === message.id}
                        started
                        panelBody={panelBody}
                        onOpen={() => openFlow(message.id, offer.kind)}
                      />
                    ) : null}
                    {superseded ? (
                      <p className="m-0 mt-2 text-xs text-muted-foreground">
                        This inquiry draft was updated later in the conversation.
                      </p>
                    ) : null}
                  </AssistantMessage>
                </TimelineRow>
              );
            })}

            {pending ? (
              <>
                <TimelineRow data-message-role="user">
                  <UserMessage
                    dimmed={pending.status === "sending"}
                    footer={
                      pending.status === "failed" ? (
                        <span className="text-destructive-foreground">Not sent</span>
                      ) : undefined
                    }
                  >
                    {pending.content}
                  </UserMessage>
                </TimelineRow>
                {pending.status === "sending" ? (
                  <TimelineRow>
                    <WorkingRow label="Working" activity="Searching the Northline documents" />
                  </TimelineRow>
                ) : null}
                {pending.status === "failed" && pending.error ? (
                  <TimelineRow>
                    <Alert variant="error" controlAlignment="first-line">
                      <CircleAlertIcon aria-hidden />
                      <AlertTitle>{pending.error.title}</AlertTitle>
                      <AlertDescription>
                        <span>{pending.error.message} Your message was not sent.</span>
                        <span className="flex flex-wrap gap-2">
                          <Button variant="outline" size="xs" onClick={chat.retry}>
                            Send again
                          </Button>
                          <Button variant="ghost" size="xs" onClick={chat.discardFailed}>
                            Remove message
                          </Button>
                        </span>
                      </AlertDescription>
                    </Alert>
                  </TimelineRow>
                ) : null}
              </>
            ) : null}
          </TimelineViewport>

          <ComposerDock
            hero={hero}
            dockRef={dockRef}
            headline={<DraftHeroHeadline>Ask about shipping, returns, or warranty</DraftHeroHeadline>}
            below={
              <div className="mx-auto flex w-full max-w-3xl flex-col items-center gap-2">
                <p className="m-0 text-xs text-muted-foreground">Try a question</p>
                <ul className="m-0 flex list-none flex-wrap justify-center gap-2 p-0">
                  {EXAMPLE_QUESTIONS.map((question) => (
                    <li key={question}>
                      <Button
                        variant="outline"
                        size="sm"
                        className="rounded-full font-normal"
                        onClick={() => askExample(question)}
                      >
                        {question}
                      </Button>
                    </li>
                  ))}
                </ul>
              </div>
            }
          >
            <ComposerForm
              label="Message to Northline Support"
              onSubmit={submit}
              editor={
                <ComposerTextarea
                  textareaRef={textareaRef}
                  aria-label="Message"
                  placeholder="Ask a question"
                  value={draft}
                  maxLength={MESSAGE_MAX_LENGTH}
                  disabled={phase !== "ready"}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={onComposerKeyDown}
                />
              }
              footerStart={
                <span className="truncate text-xs text-muted-foreground">
                  Answers come from the Northline documents.
                </span>
              }
              footerEnd={
                <ComposerSendButton busy={chat.isSending} disabled={!canSend} label="Send message" />
              }
            />
          </ComposerDock>
        </div>
      </div>

      <RightPanel
        open={panel.open}
        onClose={closePanel}
        label="Sources and inquiry"
        tabs={tabs}
        activeTabId={activeTab}
        onSelectTab={(id) => setPanel((current) => ({ ...current, tab: id === "inquiry" ? "inquiry" : "sources" }))}
        sheetControls={toggle}
        bodyRef={setPanelBody}
      >
        {activeTab === "sources" ? (
          <SourcesPanel citations={citations} highlightedIndex={panel.citationIndex} />
        ) : null}
      </RightPanel>
      <RightPanelControls>{toggle}</RightPanelControls>
    </div>
  );
}

/** The visitor chat: timeline, composer, and the side panel for sources and inquiries. */
export function ChatPage() {
  const chat = useChatContext();
  // A new conversation starts with a clean view: closed panel, empty draft.
  return <ChatView key={chat.generation} chat={chat} />;
}

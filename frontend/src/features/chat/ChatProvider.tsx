import { createContext, useContext } from "react";
import type { ReactNode } from "react";

import { useChat } from "./useChat";
import type { Chat } from "./useChat";

const ChatContext = createContext<Chat | null>(null);

/** One conversation for the whole app, so the sidebar can start a new one. */
export function ChatProvider({ children }: { children: ReactNode }) {
  const chat = useChat();
  return <ChatContext.Provider value={chat}>{children}</ChatContext.Provider>;
}

export function useChatContext(): Chat {
  const chat = useContext(ChatContext);
  if (chat === null) {
    throw new Error("useChatContext must be used inside <ChatProvider>.");
  }
  return chat;
}

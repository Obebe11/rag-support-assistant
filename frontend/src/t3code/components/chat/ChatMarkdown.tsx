/*
 * Adapted from T3 Code (apps/web/src/components/ChatMarkdown.tsx, MIT,
 * (c) 2026 T3 Tools Inc.). RAG Support Assistant keeps the wrapper classes and the
 * `.chat-markdown` styles, and renders with react-markdown and GFM only: no
 * syntax highlighting, file links, raw HTML, copy handling or streaming.
 */
import { memo } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "~/lib/utils";

const components: Components = {
  a({ href, title, children }) {
    return (
      <a href={href} title={title} target="_blank" rel="noreferrer noopener">
        {children}
      </a>
    );
  },
  table({ children }) {
    return (
      <div className="chat-markdown-table-container overflow-x-auto" data-expanded="true">
        <table>{children}</table>
      </div>
    );
  },
};

const remarkPlugins = [remarkGfm];

interface ChatMarkdownProps {
  text: string;
  className?: string;
}

function ChatMarkdownImpl({ text, className }: ChatMarkdownProps) {
  return (
    <div
      className={cn(
        "chat-markdown w-full min-w-0 text-sm leading-relaxed text-foreground/80 [overflow-wrap:anywhere] [word-break:break-word]",
        className,
      )}
    >
      <ReactMarkdown remarkPlugins={remarkPlugins} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

export const ChatMarkdown = memo(ChatMarkdownImpl);

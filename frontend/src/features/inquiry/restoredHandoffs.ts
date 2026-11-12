import type { InquiryRead, MessageRead } from "../../api/client";

/**
 * After a reload, find the knowledge-gap message each handoff request belongs to.
 *
 * The server keeps a handoff with its conversation, not with a message. A
 * request is created after the reply it answers, so it goes to the latest
 * knowledge-gap reply that is older than the request. When the notes still hold
 * the visitor's question word for word, the reply to that question wins. A
 * message shows its newest request.
 */
export function restoredHandoffs(messages: MessageRead[], inquiries: InquiryRead[]): Map<string, InquiryRead> {
  const gaps: { id: string; createdAt: number; question: string }[] = [];
  let question = "";
  for (const message of messages) {
    if (message.role === "user") {
      question = message.content.trim();
    } else if (message.answer_type === "knowledge_gap") {
      gaps.push({ id: message.id, createdAt: Date.parse(message.created_at), question });
    }
  }

  const byMessage = new Map<string, InquiryRead>();
  for (const inquiry of inquiries) {
    if (inquiry.kind !== "handoff") continue;
    const createdAt = Date.parse(inquiry.created_at);
    const earlier = gaps.filter((gap) => gap.createdAt <= createdAt);
    const candidates = earlier.length > 0 ? earlier : gaps;
    const notes = (inquiry.notes ?? "").trim();
    const target = candidates.filter((gap) => gap.question === notes).at(-1) ?? candidates.at(-1);
    if (target) byMessage.set(target.id, inquiry);
  }
  return byMessage;
}

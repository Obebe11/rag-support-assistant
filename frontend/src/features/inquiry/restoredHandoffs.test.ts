import { describe, expect, it } from "vitest";

import { assistantMessage, inquiryFixture, knowledgeGapReply, userMessage } from "../../mocks/fixtures";
import { restoredHandoffs } from "./restoredHandoffs";

const at = (minute: number) => `2026-11-11T10:${String(minute).padStart(2, "0")}:00Z`;

const handoff = (minute: number, notes: string) =>
  inquiryFixture({ id: `handoff-${minute}`, kind: "handoff", notes, created_at: at(minute) });

describe("restoredHandoffs", () => {
  const firstGap = { ...knowledgeGapReply(), created_at: at(1) };
  const secondGap = { ...knowledgeGapReply(), created_at: at(3) };
  const messages = [
    userMessage("Do you ship to Canada?", { created_at: at(1) }),
    firstGap,
    userMessage("Do you install printers?", { created_at: at(3) }),
    secondGap,
    userMessage("What does the warranty cover?", { created_at: at(5) }),
    assistantMessage({ answer_type: "grounded", created_at: at(5) }),
  ];

  it("puts a request on the latest knowledge-gap reply that is older than it", () => {
    const edited = handoff(2, "Shipping to Toronto, please.");
    const later = handoff(6, "Something else entirely.");

    const byMessage = restoredHandoffs(messages, [edited, later]);

    expect(byMessage.get(firstGap.id)).toBe(edited);
    expect(byMessage.get(secondGap.id)).toBe(later);
  });

  it("prefers the reply to the question the notes repeat", () => {
    // Made from the first reply after the second one had arrived.
    const request = handoff(4, "Do you ship to Canada?");

    expect(restoredHandoffs(messages, [request]).get(firstGap.id)).toBe(request);
  });

  it("shows the newest request of a message and ignores purchase inquiries", () => {
    const older = handoff(2, "Do you ship to Canada?");
    const newer = { ...handoff(2, "Do you ship to Canada?"), id: "handoff-newer" };
    const purchase = inquiryFixture({ created_at: at(2) });

    const byMessage = restoredHandoffs(messages, [purchase, older, newer]);

    expect([...byMessage.values()]).toEqual([newer]);
  });

  it("restores nothing without a knowledge-gap reply", () => {
    expect(restoredHandoffs(messages.slice(4), [handoff(6, "Do you ship to Canada?")]).size).toBe(0);
  });
});

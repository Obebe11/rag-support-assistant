import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";

import { timing } from "../lib/timing";

// Poll fast, so delivery and indexing progress within a test's default timeout.
timing.deliveryPollMs = 20;
timing.documentsPollMs = 20;

/** Media queries that match in the current test; empty means a wide window. */
const matchingQueries = new Set<string>();

/** Make `window.matchMedia(query)` match until the end of the test. */
export function matchMediaQuery(query: string): void {
  matchingQueries.add(query);
}

// jsdom has no layout: these browser APIs are missing and the UI kit expects them.
window.matchMedia = (query: string): MediaQueryList => ({
  matches: matchingQueries.has(query),
  media: query,
  onchange: null,
  addEventListener: () => undefined,
  removeEventListener: () => undefined,
  addListener: () => undefined,
  removeListener: () => undefined,
  dispatchEvent: () => false,
});

class ResizeObserverStub implements ResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
window.ResizeObserver = ResizeObserverStub;

Element.prototype.scrollIntoView = () => undefined;
Element.prototype.getAnimations = () => [];

// Uploads: Node's `fetch` cannot send jsdom's `FormData`, and with jsdom's
// `File` in the global scope it cannot build or parse a multipart body either.
// Tests therefore use Node's `File`, `Blob`, `FormData` and `Request`; Vitest's
// own `Request` expects jsdom bodies and would try to convert these.
const nodeBuffer = (await import("node:buffer" as string)) as { Blob: typeof Blob; File: typeof File };
window.File = nodeBuffer.File;
window.Blob = nodeBuffer.Blob;
window.FormData = (await new Response(new URLSearchParams()).formData()).constructor as typeof FormData;
window.Request = Object.getPrototypeOf(window.Request) as typeof Request;

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  matchingQueries.clear();
});

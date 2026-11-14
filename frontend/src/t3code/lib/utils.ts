/*
 * Adapted from T3 Code (apps/web/src/lib/utils.ts, MIT, (c) 2026 T3 Tools Inc.).
 * RAG Support Assistant keeps only `cn`; the id and platform helpers are not needed here.
 */
import { type CxOptions, cx } from "class-variance-authority";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: CxOptions) {
  return twMerge(cx(inputs));
}

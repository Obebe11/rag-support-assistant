/**
 * Polling intervals, in milliseconds. One place, so the tests can shorten them
 * (see `src/test/setup.ts`); the app itself never changes them.
 */
export const timing = {
  /** How often the delivery status of a confirmed inquiry is read. */
  deliveryPollMs: 2000,
  /** How often the document list is read while a document is being indexed. */
  documentsPollMs: 3000,
};

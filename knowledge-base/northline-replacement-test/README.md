# Northline Document Replacement Test

This folder holds superseded versions of two documents from the [Northline knowledge base](../northline/README.md). They are used to check that replacing a document removes its outdated chunks from active retrieval.

**These files are not part of the active corpus.** Do not ingest them into the demo knowledge base. Northline Office Equipment is a fictional company, and these documents are original work under the MIT License of the repository.

## Files

`manifest.json` uses the same format as the corpus manifest. Each entry has the same `doc_id` as the current document it precedes, with a lower `version`.

| `doc_id` | Superseded version (this folder) | Current version (active corpus) |
| --- | --- | --- |
| `northline-returns-policy` | 1.3, `returns-policy-v1.3.md` | 2.0, `../northline/documents/returns-policy.md` |
| `northline-shipping-policy` | 2.2, `shipping-policy-v2.2.md` | 3.0, `../northline/documents/shipping-policy.md` |

## Facts that differ between versions

Use these facts to tell which version an answer is based on.

| Question | Superseded version | Current version |
| --- | --- | --- |
| How long is the return window? | 45 days (Returns Policy 1.3) | 30 days (Returns Policy 2.0) |
| What is the restocking fee for an opened item? | 20% | 15% |
| How long is an RMA number valid? | 10 days | 14 days |
| How soon is a refund issued after the return arrives? | Within 10 business days | Within 7 business days |
| What does Standard Ground shipping cost? | $12.95 per order (Shipping Policy 2.2) | $14.95 per order (Shipping Policy 3.0) |
| From what order value is Standard Ground free? | $750 | $500 |
| What is the cut-off for same-day shipping? | 12:00 noon Pacific Time | 2:00 p.m. Pacific Time |
| How soon must transit damage be reported? | Within 3 business days | Within 5 business days |

The FAQ in the active corpus repeats the current return window and shipping rate. For a clean test, use a knowledge base that contains only the document under test, or ask about facts the FAQ does not repeat, such as the restocking fee, the RMA validity or the refund time.

## Replacement test

1. Start with an empty test knowledge base. Do not use the demo knowledge base.
2. Ingest the superseded version of a document from this folder.
3. Ask the questions above. The answers and citations must match the "Superseded version" column and show the old version number.
4. Replace the document with the current version from `../northline/documents/`, using the same `doc_id`.
5. Ask the same questions. The answers must match the "Current version" column. No answer and no citation may contain a value or a version number from the superseded document.
6. Confirm that retrieval returns no chunk of the superseded version.

## Deletion test

1. Ingest the current Returns Policy into an empty test knowledge base and confirm that a return window question is answered with a citation.
2. Delete the document.
3. Ask the same question. The assistant must acknowledge the knowledge gap and offer a human handoff, and retrieval must return no chunk of the deleted document.

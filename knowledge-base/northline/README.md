# Northline Knowledge Base

This folder is the knowledge base for the main Handoff AI demo scenario: a support and lead intake assistant for an office equipment supplier.

**Northline Office Equipment is a fictional company.** Every product, SKU, price, policy, address, phone number and email address here was written for this demo. Phone numbers use the reserved 555-01xx range and email addresses use the reserved `example.com` domain. Any resemblance to a real business is unintended.

## Contents

13 documents: 10 Markdown files and 3 multi-page PDFs with a text layer.

| `doc_id` | Document | Format | Category |
| --- | --- | --- | --- |
| `northline-faq` | Frequently Asked Questions | Markdown | faq |
| `northline-shipping-policy` | Shipping Policy | Markdown | policy |
| `northline-returns-policy` | Returns Policy | Markdown | policy |
| `northline-warranty-policy` | Warranty Policy | PDF, 3 pages | policy |
| `northline-ordering-payment-terms` | Ordering and Payment Terms | Markdown | policy |
| `northline-service-maintenance-guide` | Service and Maintenance Guide | PDF, 4 pages | service |
| `northline-volume-orders-quotes` | Volume Orders and Quotes | Markdown | sales |
| `northline-contact-support-hours` | Contact and Support Hours | Markdown | contact |
| `northline-product-p240` | P-240 Monochrome Laser Printer | Markdown | product |
| `northline-product-c360` | C-360 Color Multifunction Printer | PDF, 3 pages | product |
| `northline-product-s300` | S-300 Cross-Cut Shredder | Markdown | product |
| `northline-product-l125` | L-125 Thermal Laminator | Markdown | product |
| `northline-product-lp420` | LP-420 Thermal Label Printer | Markdown | product |

```text
northline/
├── manifest.json     list of documents; the source of truth for ingestion
├── documents/        the files to ingest
├── pdf-source/       Markdown sources of the PDFs and the build script
└── README.md
```

Ingest only the files listed in `manifest.json`. The files in `pdf-source/` duplicate the PDF content and must not be indexed.

## Manifest

`manifest.json` has one entry per document:

| Field | Meaning |
| --- | --- |
| `doc_id` | Stable identifier. It stays the same when a document is replaced by a newer version. Evaluation cases refer to documents by `doc_id`. |
| `title` | Document title to show in citations. |
| `version` | Document version, for example `2.0`. |
| `effective_date` | Date the version takes effect, `YYYY-MM-DD`. |
| `category` | One of `faq`, `policy`, `service`, `sales`, `contact`, `product`. |
| `format` | `markdown` or `pdf`. |
| `path` | File path relative to this folder. |
| `page_count` | PDF only: number of pages. |
| `source_path` | PDF only: the Markdown source the PDF is built from. |

## Rebuilding the PDFs

The PDFs are generated from the Markdown files in `pdf-source/` with [ReportLab](https://www.reportlab.com/opensource/) (BSD license). The script declares its dependencies inline, so [uv](https://docs.astral.sh/uv/) can run it without a project environment. Run it from the repository root:

```bash
uv run knowledge-base/northline/pdf-source/build_pdfs.py          # rebuild the PDFs
uv run knowledge-base/northline/pdf-source/build_pdfs.py --check  # verify without rebuilding
```

A `<!-- pagebreak -->` line in a source starts a new PDF page. Evaluation cases cite PDF page numbers, so the build fails if the content of a source page does not fit on one PDF page. After building, the script extracts the text layer with [pypdf](https://pypdf.readthedocs.io/) (BSD license) and confirms that each source page matches the same PDF page. The output is deterministic: rebuilding unchanged sources gives identical files.

After you edit a PDF source, rebuild the PDF, update `version`, `effective_date` and `page_count` in `manifest.json`, and run `python3 evals/validate_cases.py`.

## Consistency rules

Facts that appear in more than one document must agree. The policy documents are the primary source; the FAQ and the product sheets repeat some facts in short form. When you change one of the following, update every document that states it:

- return window, restocking fee and RMA rules (Returns Policy, FAQ, Shipping Policy);
- shipping rates and free shipping thresholds (Shipping Policy, FAQ, Volume Orders and Quotes, C-360 sheet);
- warranty periods and advance replacement (Warranty Policy, Service and Maintenance Guide, FAQ, product sheets);
- prices, SKUs and maintenance intervals (product sheets, Service and Maintenance Guide, FAQ);
- phone numbers, email addresses and hours (Contact and Support Hours, and every document that mentions a team).

## Deliberate gaps

The corpus says nothing on the topics below. They are left out on purpose, so that the assistant can be tested on questions it must not answer from the documents. The expected behavior is to acknowledge the knowledge gap and offer a human handoff. Do not add these topics without updating the evaluation cases in `evals/cases/unanswerable.json`.

| Topic the corpus does not cover | Nearest content that is covered |
| --- | --- |
| Shipping outside the United States | The Shipping Policy covers US deliveries only. |
| Leasing, rental and installment financing | Payment methods and Net 30 terms. |
| Trade-in, take-back and recycling of old equipment | None. |
| Price matching | List prices, volume discounts and quotes. |
| Sales tax and tax exemption certificates | Prices are stated without shipping; tax is not mentioned. |
| Linux support for any printer | Product sheets list Windows and macOS only. |
| Noise level of the S-300 shredder | The P-240 sheet lists a noise level; the S-300 sheet does not. |
| On-site installation and setup by a technician | Remote troubleshooting and repair at the service center. |
| Reseller, dealer and distributor programs | Volume discounts for end customers. |
| Discounts for schools, nonprofits and public bodies | Volume discounts based on order size. |

## Related folders

- [`../northline-replacement-test/`](../northline-replacement-test/README.md) holds superseded versions of two documents for the document replacement test. They are not part of this corpus.
- [`../../evals/`](../../evals/README.md) holds the evaluation cases that refer to this corpus.
- `demo-docs/` at the repository root is a separate corpus for an alternative scenario. Keep the two knowledge bases apart.

## License

The documents in this folder are original work written for this project and are released under the MIT License of the repository. They contain no third-party text.

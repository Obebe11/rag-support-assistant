# RAG Demo Documents

[odoo/](odoo/README.md) contains 20 authentic English articles from the official Odoo 19 documentation: CRM, lead scoring, support tickets and ratings, quotations, pricing, invoicing, delivery, eCommerce checkout and subscriptions. Sources, version and licensing information are preserved. No private data is included.

This is a ready **alternative corpus for a business software AI support demo**. The main demo scenario uses a fictional equipment supplier, Northline Office Equipment; Odoo documents do not establish its shipping, returns or warranty policies. Keep these scenarios in separate knowledge bases. The workflow for this corpus is: question about using Odoo → answer with a source citation → offer a human handoff if the information is insufficient. An Odoo API integration is not required for this demo.

[odoo-replacement-test/](odoo-replacement-test/README.md) holds two older Odoo 18 versions of corpus articles. They are excluded from retrieval and used only to test document replacement.

Articles are stored in their original `.rst` text format, without screenshots. The application does not load this corpus: `make seed` loads the Northline knowledge base, and the ingestion pipeline reads Markdown and PDF, not `.rst`.

[DEMO-QUESTIONS.md](DEMO-QUESTIONS.md) contains sample questions for this corpus. These are proposed checks, not evaluation results: the evaluation in [`evals/`](../evals/README.md) runs on the Northline knowledge base only.

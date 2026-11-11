# Odoo 19 — English RAG demo corpus

20 official English articles about CRM, sales, pricing, invoicing, delivery, eCommerce checkout, subscriptions and customer support. Approximately 167 KB of original article text. This is a small corpus for a documentation assistant demo, not the full Odoo manual.

## Documents

| Local source | Published documentation |
| --- | --- |
| [Invoicing policies](invoicing_policy.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/sales/sales/invoicing/invoicing_policy.html) |
| [Down payments](down_payment.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/sales/sales/invoicing/down_payment.html) |
| [Returns and refunds](returns.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/sales/sales/products_prices/returns.html) |
| [Deliveries and invoices to different addresses](different_addresses.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/sales/sales/sales_quotations/different_addresses.html) |
| [Create quotations](create_quotations.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/sales/sales/sales_quotations/create_quotations.html) |
| [Create leads (from email or manually)](email_manual.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/sales/crm/acquire_leads/email_manual.html) |
| [Convert leads into opportunities](convert.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/sales/crm/acquire_leads/convert.html) |
| [Receiving tickets](receiving_tickets.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/services/helpdesk/overview/receiving_tickets.html) |
| [Service level agreements (SLA)](sla.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/services/helpdesk/overview/sla.html) |
| [After-Sales services](after_sales.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/services/helpdesk/advanced/after_sales.html) |
| [Assign leads with predictive lead scoring](lead_scoring.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/sales/crm/track_leads/lead_scoring.html) |
| [Customer ratings](ratings.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/services/helpdesk/overview/ratings.html) |
| [Quotation templates](quote_template.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/sales/sales/sales_quotations/quote_template.html) |
| [Online signatures for order confirmations](get_signature_to_validate.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/sales/sales/sales_quotations/get_signature_to_validate.html) |
| [Online payment order confirmation](get_paid_to_validate.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/sales/sales/sales_quotations/get_paid_to_validate.html) |
| [Pricelists](pricing.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/sales/sales/products_prices/prices/pricing.html) |
| [Discounts](discounts.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/sales/sales/products_prices/prices/discounts.html) |
| [Delivery methods](setup_configuration.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/shipping_receiving/setup_configuration.html) |
| [Ordering and checkout](checkout.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/websites/ecommerce/checkout.html) |
| [Renew subscriptions](renewals.rst) | [Official article](https://www.odoo.com/documentation/19.0/applications/sales/subscriptions/renewals.html) |

## Scope and usage

Use these documents to demonstrate answering questions about Odoo workflows with source citations. This corpus describes how Odoo software works; it does not establish a merchant's return window, shipping prices or warranty terms.

The `.rst` files are original UTF-8 reStructuredText sources, readable as text. They contain Sphinx roles, directives and relative references. Images and linked articles are not downloaded. A future ingestion pipeline should handle this markup or convert it before chunking; no ingestion code is included here.

Ingest only the twenty article files. Keep this README, the license, manifest and the separate demo questions outside retrieval. Preserve article title, source URL and version as chunk metadata. Link citations to the official article URLs in `SOURCES.json`. Do not pretend the chatbot has access to live Odoo accounts or order records.

## Attribution and license

Source: [Odoo documentation](https://github.com/odoo/documentation), Odoo S.A. and contributors, version 19.0.

The articles are distributed under [Creative Commons Attribution-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-sa/4.0/). The complete upstream license is in [LICENSE](LICENSE). Preserve attribution, the license link and notices when sharing this corpus; identify changes and apply the required ShareAlike terms to adaptations. This notice concerns the documentation corpus.

Files were copied byte-for-byte without editorial changes. All twenty articles are pinned to the same repository commit. `SOURCES.json` records that commit, retrieval times, original URLs, byte sizes and SHA-256 hashes. The original sources may reference assets outside this selection. This is an independent portfolio demo, with no claimed affiliation or endorsement by Odoo.

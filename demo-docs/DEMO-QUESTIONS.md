# Example demo questions

English questions for the Odoo 19 documentation corpus. These are proposed manual checks, not a completed evaluation or proof of model performance. Keep this file outside the retrieval corpus.

## Questions covered by the selected articles

1. “What is the difference between invoicing ordered quantities and delivered quantities?” — `invoicing_policy.rst`.
2. “How do I request a percentage-based down payment?” — `down_payment.rst`.
3. “How do I process a return after an invoice has already been issued?” — `returns.rst`.
4. “Can I send an invoice to a different address from the delivery address?” — `different_addresses.rst`.
5. “How can incoming emails create CRM leads?” — `email_manual.rst`.
6. “What should I check if a similar lead already exists before converting a lead?” — `convert.rst`.
7. “Which channels can customers use to submit Helpdesk tickets?” — `receiving_tickets.rst`.
8. “Why is the Return button missing from my Helpdesk ticket?” — `after_sales.rst`.

For each answer, check that the cited article actually supports the explanation and that conditions and prerequisites are retained. Finding a related article alone does not establish answer correctness.

## Questions requiring an explicit limitation

9. “What is Northline's 30-day return policy?” — No Northline merchant policy is included. Explain that the documents describe Odoo workflows and do not establish a return deadline.
10. “Has order SO042 been delivered, and can you refund it now?” — No live customer account or order data is available. Do not invent an order status or claim to have executed a refund. Offer handoff if implemented.

## Questions for the added articles

11. “What data does predictive lead scoring use to estimate the probability of winning a lead?” — `lead_scoring.rst`. Historical CRM data on which leads and opportunities were won and lost.
12. “On which Helpdesk stage should I set the ratings request email?” — `ratings.rst`. Only on a stage folded in the Kanban view, because tickets in a folded stage are considered closed.
13. “Where do I turn on quotation templates?” — `quote_template.rst`. In the Sales app settings, by enabling *Quotation Templates* and saving.
14. “Which signature options does a customer have when signing a quotation online?” — `get_signature_to_validate.rst`. *Auto*, *Draw* or *Load*.
15. “What setting lets customers confirm an order by paying online?” — `get_paid_to_validate.rst`. The *Online Payment* setting in the Sales app.
16. “Can a salesperson change the price that a pricelist suggests on a sales order?” — `pricing.rst`. Yes. Pricelists only suggest prices, and they can always be overridden on the sales order.
17. “What does a negative value in the Disc.% column do?” — `discounts.rst`. It increases the price instead of applying a discount.
18. “Which module do I need to calculate shipping costs on sales orders and in eCommerce?” — `setup_configuration.rst`. The *Delivery Costs* module.
19. “Can I add a Buy now button to the online store?” — `checkout.rst`. Yes; the article also covers changing the Add to Cart behavior.
20. “What must be in place before I can create a renewal quotation for a subscription?” — `renewals.rst`. A confirmed quotation with a subscription product, a configured recurring plan, and an invoiced and registered initial payment.

## Easily confused articles

Each question has a similar-looking article that gives a different answer. The expected source must rank above the distractor.

21. “What setting lets customers confirm an order by paying, not by signing?” — Expected: `get_paid_to_validate.rst`. Distractor: `get_signature_to_validate.rst`.
22. “How do I raise the price of a single order line by a percentage?” — Expected: `discounts.rst` (negative Disc.%). Distractor: `pricing.rst`.
23. “When should a customer receive a request to rate our support?” — Expected: `ratings.rst`. Distractor: `sla.rst`.
24. “How does the return process differ before and after the invoice is issued?” — Expected: `returns.rst`. Distractor: `invoicing_policy.rst`.
25. “What happens if I convert a lead with a 100% probability into an opportunity?” — Expected: `convert.rst` (an error message appears). Distractor: `lead_scoring.rst`.

## Document replacement checks

Two questions verify that replacing a document removes outdated chunks. The older Odoo 18 files and the full procedure are in [odoo-replacement-test/](odoo-replacement-test/README.md).

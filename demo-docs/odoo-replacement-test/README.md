# Odoo 18 — document replacement test

Two official Odoo **18.0** articles whose **19.0** versions are in [`../odoo/`](../odoo/README.md). They are not part of the active corpus. Use them only to test that replacing a document removes its outdated chunks from retrieval.

## Test procedure

1. Index the 18.0 file from this folder.
2. Ask the test question and confirm the answer reflects the 18.0 text.
3. Replace it with the 19.0 file from `../odoo/` under the same document ID.
4. Ask again. The answer must reflect only the 19.0 text, and no 18.0 chunk may appear among the retrieved sources.

| File | What changed in 19.0 | Test question | Expected answer after replacement |
| --- | --- | --- | --- |
| [convert.rst](convert.rst) | The warning near the conversion steps now says that converting a lead with a 100% probability results in an error. In 18.0 that warning was about the *Similar Leads* smart button. | "What happens if I try to convert a lead with a 100% probability into an opportunity?" | An error message appears. With only the 18.0 version indexed, the documents do not answer this. |
| [down_payment.rst](down_payment.rst) | The amount field in the *Create invoice(s)* pop-up is named **Down Payment** instead of **Down Payment Amount**. The draft invoice first shows a *Down Payment* line item; the *Down Payments* section appears after confirmation. | "Which field do I fill in to set a fixed down payment amount?" | **Down Payment**. The old name *Down Payment Amount* must not appear. |

These are proposed checks, not results from a working system.

## Attribution and license

Source: [Odoo documentation](https://github.com/odoo/documentation), Odoo S.A. and contributors, version 18.0, pinned to commit `fbcd35b2423633d45390466cad2bae1f644fb759`.

The articles are distributed under [Creative Commons Attribution-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-sa/4.0/). The complete upstream license is in [LICENSE](LICENSE). Files were copied byte-for-byte without editorial changes; `SOURCES.json` records URLs, sizes and SHA-256 hashes. This is an independent portfolio demo, with no claimed affiliation or endorsement by Odoo.

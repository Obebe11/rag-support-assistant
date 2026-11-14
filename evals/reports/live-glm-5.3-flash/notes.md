### What this run is

The first run of the 40 cases with a live LLM and a live embedding model: `z-ai/glm-5.3-flash` for the replies and `amazon/titan-embed-text-v2` for the search, both through OpenRouter, with `LLM_REASONING_EFFORT=low`. The LLM judge was on and used the same model. It is one run; a second run with the same settings can give different replies, because the model output is not fixed.

The code is commit `4b91419`, the change that makes a clarifying question or a knowledge gap cite the documented facts it names. The report says "with uncommitted changes": at run time the working tree also had two text edits in `README.md` and `evals/README.md`, and no code change. No threshold, pattern, prompt or case was changed after the run.

Prices per token were not configured for this run, so the report gives tokens and no cost.

### Compared with the local baseline

| | [`local-baseline`](../local-baseline/report.md) (no LLM) | This run (live LLM and embeddings) |
| --- | --- | --- |
| Cases after the automated first pass | 8 pass, 20 fail, 12 need review | 15 pass, 3 fail, 22 need review |
| Cases after the review of open checks | 20 pass, 20 fail | 37 pass, 3 fail |
| Response type as expected | 30 of 50 turns | 48 of 50 turns |
| Expected source in the top five, search for the message alone | 21 of 33 turns | 29 of 33 turns |
| Required facts found | 18 of 68 | 63 of 68 |

The open checks of both runs were reviewed by an AI coding agent, not by a person. Here a second AI agent drafted verdicts on its own and agreed on all 40 items.

### Why the three cases failed

- **ans-16** ("We want to order 12 S-300 shredders in one order. What discount would we get, and would shipping be free?"). The message is a purchase request and a question, so the chat asks the LLM about the question and then offers the inquiry. The LLM answered the question with a clarifying question. The chat does not merge a clarifying question into an inquiry offer, so the reply was the plain offer and the discount and freight questions stayed unanswered (`usage.note`: "The question in the message got no answer (clarification)."). The retrieval behind the reply had the volume discount and freight sections, but not the S-300 specifications with the shipping weight.
- **gap-01** ("Do you ship to Canada?"). The model gave a grounded reply: the Shipping Policy "covers deliveries within the United States only, so Canada deliveries aren't covered". The policy says it covers deliveries within the United States; it says nothing about other countries. The reply presents an inference as policy and offers no handoff. The case expects a knowledge gap.
- **multi-02, turn 1** ("We received a P-240 ten days ago ... Can we send it back?"). The reply explains the refund by item condition but not the 30-day return window or the RMA number. Neither the search nor the retrieval behind the reply had the "Return window" or "Return authorization" sections in the top five; they ranked the refund table first. Turns 2 and 3 of the case passed.

### Clarifying questions and knowledge gaps now cite their facts

Both clarification turns in the cases cited their sources: multi-01 turn 1 (four passages) and multi-03 turn 1 (three passages; the question lists the toner prices of each printer). Ten of the eleven knowledge-gap replies named a related documented fact, such as a list price or the Sales contact, and cited it. No stored reply fell back to the general clarifying question or to the standard knowledge-gap text. In ans-16 the clarifying question was dropped from the reply, so its text and citations were not stored.

### What the LLM judge found

- The judge decided all 40 open checks. It agrees with the review on 39; on gap-10 (`must_not_include[1]`) it read "Our documents don't mention any special discounts for schools or nonprofit organizations" as a statement that no such discount exists. The review counts it as a correct knowledge gap.
- It marked 17 of 33 grounded replies as not supported by their cited excerpts. Every flagged fact was checked against the corpus: all 17 are stated in the section that the reply cites, outside the 500-character excerpt the judge sees. None is missing from the corpus. This number measures the excerpt limit of the judge more than the replies.

### Reply details worth knowing

These do not fail a check, but a reader of the replies would notice them:

- gap-08: the reply contains a bracketed excerpt number ("[2]"), which the prompt forbids.
- multi-05 turn 2: the reply says to start a return through Customer Support. The Returns Policy says to request an RMA number on the Orders page or by email.
- ans-02: "Only unopened, sealed items get 100% back" is true for a change-of-mind return; a defective or damaged item also gets 100%.
- multi-01 turn 2: "damage from ... using the wrong lubricants is not covered" is broader than the guide, which names aerosol lubricants and petroleum-based oils.

### What this run does not show

- One model on one demo corpus. Another model, another reasoning setting or other documents can give different results.
- The intent detector's LLM calls are not counted in the reply tokens.
- No inquiry was confirmed, so the CRM was not exercised.

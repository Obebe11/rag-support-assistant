### What this run is

The same 40 cases in the same local demo modes as the [baseline](../local-baseline/report.md), after one change in the chat: a message that states a purchase request and also asks a question now gets the answer to the question first and the inquiry offer after it. Before the change such a message got the offer only. No threshold, pattern or wording was changed to make a case pass, and no case was edited.

### What changed against the baseline

One reply of 50 changed: ans-16, "We want to order 12 S-300 shredders in one order. What discount would we get, and would shipping be free?". Every other reply has the same answer type, text and cited documents as in the baseline.

| | Baseline | This run |
| --- | --- | --- |
| Cases after the automated first pass | 8 pass, 20 fail, 12 need review | 8 pass, 20 fail, 12 need review |
| Cases after the manual review | 20 pass, 20 fail | 20 pass, 20 fail |
| Response type as expected | 30 of 50 turns | 31 of 50 turns |
| Expected source in the top five | 21 of 33 turns | 21 of 33 turns |
| Expected source cited | 13 of 33 turns | 13 of 33 turns |
| Required facts found | 18 of 68 | 20 of 68 |

- **ans-16 before:** an inquiry offer and nothing else. The question stayed unanswered.
- **ans-16 now:** the reply quotes the section "Shipping for volume orders" (standard LTL freight is free on orders of $2,500 or more), cites it, and then offers the inquiry with the draft for 12 S-300 shredders. The reply is still an `inquiry_offer`; the runner scores it as `grounded`, because that is how the question in it was answered (`usage.question_answer_type`).
- **ans-16 still fails.** The reply does not name the 5% discount, and the expected passages (the discount table, the S-300 specifications, the freight section of the Shipping Policy) are not cited. This is the local mode again: it quotes the passage that shares the most words with the question and cannot combine three documents or compute a total.
- **One of the two newly found facts is a weak match.** The check "The order ships by LTL freight because its shipping weight is over 150 lb" passes on the word "freight". The reply says that freight is free above $2,500; it does not say that this order ships by freight. The other fact, "Standard freight is free because the merchandise subtotal is $2,500 or more", is stated by the quote. Neither changes the status of the case.

For why the other turns failed, see the notes of the baseline report: they apply to this run unchanged.

### What was not measured

No live LLM and no live embedding model, as in the baseline: no API key was available. In the LLM mode the model reads the request and the question itself, so this run says nothing about how well a live model handles such messages.

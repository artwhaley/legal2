# Mission and invariants

## Product objective

The product helps a human digest a mountain of message data. A conversational
search is advisory analysis, not an automatic legal canon. The user wants the
best available answer on every run and may inspect borderline results
personally.

The governing rule is:

> Return every intelligible result. Prefer overcollection to omission. Verify
> source identity mechanically, but never discard an expensive readable answer
> because the model's structure, ranking, or categorization is imperfect.

## Binding invariants

1. A readable final-model response reaches the user unchanged.
2. Validation annotates readable synthesis; it does not gate publication.
3. Valid work from one window survives malformed ranges or failure in another
   window.
4. Valid evidence ranges, completed windows, the canonical ledger, and raw
   model responses are never discarded because a later optional stage fails.
5. Only references that cannot be tied to real supplied messages/ranges are
   excluded from verified evidence.
6. Fabricated IDs are isolated granularly. They never poison valid sibling
   citations, findings, ranges, windows, or the complete answer.
7. The server never guesses an opaque ID, fuzzily matches one, shortens one,
   or substitutes a nearby source.
8. Only deterministic, one-interpretation corrections are permitted and every
   correction is reported.
9. There is no `direct_evidence`, `useful_context`, or `not_responsive`
   concept anywhere in the active runtime, contracts, prompts, admin, client,
   scripts, or production tests.
10. Result ordering uses exactly `high_probability` and
    `lower_probability`. These labels describe likely responsiveness to the
    user's question, not truth, legal weight, or calibrated statistical
    confidence.
11. High-probability results are presented first. A visible boundary separates
    lower-probability, borderline, contextual, or unclassified candidates.
12. No numeric confidence score, threshold, arbitrary result count, or
    relevance cutoff is added.
13. Every validated extraction range remains inspectable even when synthesis
    omits or fails to classify it.
14. Actual transcript text shown as evidence comes from the client-owned EVW
    using verified message IDs, never from model-generated quotation text.
15. A search may terminate as `failed` only when no useful answer and no
    validated evidence can be returned, or the request cannot be executed at
    all.
16. `complete_with_warnings` and `partial` are successful terminal results,
    not failure popups.
17. Empty/unusable model output triggers a targeted retry of that operation
    only. Completed planning, retrieval, embeddings, windows, ledger work, and
    other model calls are not repeated.
18. Readable prose that violates JSON/schema expectations is intelligible and
    is returned; it is not automatically rerun.
19. Existing provider HTTP retries remain explicit and visible. No hidden
    provider/model fallback is introduced.
20. Ledger compaction remains a loud fallback. Failure of compaction preserves
    and returns the original ledger.
21. The server remains stateless and EVW-blind. The Python client remains test
    equipment. Flutter and EVW schema/lifecycle are out of scope.

## Probability semantics

`high_probability` means the synthesis model considers the result strongly
responsive to the frozen analysis plan.

`lower_probability` means the result may still help answer the plan but is
borderline, uncertain, context-dependent, indirect, weakly connected, or was
not classified successfully.

Neither label certifies factual truth. Both sections are user-visible.

## Hard failure boundary

Hard failure is reserved for:

- invalid request or incompatible frozen plan before meaningful work;
- impossible window planning, such as a single unsplittable message;
- no usable extraction output from any window after targeted attempts and no
  readable synthesis;
- no readable synthesis and no validated evidence to return;
- an internal failure that prevents preserved artifacts from being assembled;
- explicit cancellation, which remains cancellation rather than a partial
  persisted answer unless the product already has a separately specified
  resume contract.

Everything else returns the best available result with warnings.


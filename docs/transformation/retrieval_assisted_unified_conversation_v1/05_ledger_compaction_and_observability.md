# Ledger compaction and observability

## Canonical ledger

The ledger built from extraction outputs is immutable and authoritative for the
request. It stores every validated original evidence range with exact message
excerpt, summary, relevance, window, and stable range ID.

Compaction never replaces, edits, deletes, filters, reorders, or truncates this
canonical ledger. Final response assembly uses the original range boundaries,
summary, and relevance for every original range ID. Transcript text remains in
the request-local canonical record for synthesis/validation but is not
duplicated into the final wire result because the client already owns it.

## Direct synthesis first

Before synthesis, exact-count the complete generated provider payload
containing:

- system prompt;
- response schema and provider wrapper;
- question;
- complete coverage report;
- metadata for every range;
- every complete original evidence record and excerpt;
- output reservation and safety margin.

Emit `ledger_synthesis_preflight` for every request.

If it fits, call synthesis directly. `compaction_applied=false`.

## Retained fallback compaction

If and only if exact preflight does not fit the active synthesis model's usable
input budget, invoke hierarchical compaction.

Public/admin terminology is **ledger compaction**, not “lossless reduction.”
The mechanism guarantees range-ID coverage but an LLM summary cannot be proven
semantically lossless. The admin explanation must say this plainly.

Algorithm:

1. Emit and log `ledger_compaction_required` at WARNING severity with exact
   required/available/excess tokens, original range count, evidence message
   count, and maximum depth.
2. Partition complete current-level records into the largest chronological
   groups that exactly fit the configured `ledger_compaction` operation.
3. Never split or drop one ledger record. If one record cannot fit, fail
   `LEDGER_COMPACTION_RECORD_TOO_LARGE`.
4. Call `ledger_compaction` for every group.
5. Require:
   - matching group ID;
   - every original covered range ID exactly once;
   - original range-ID order;
   - one valid disposition/rationale per covered ID;
   - no unknown ID.
6. Validate global covered IDs after every level against the complete canonical
   ledger.
7. Repeat only while direct synthesis still does not fit and configured maximum
   depth remains.
8. If depth is exhausted, fail `LEDGER_COMPACTION_DEPTH_EXCEEDED`.
9. Synthesis always receives complete ledger metadata for every original range
   plus the highest-level group summaries.
10. Final synthesis must return one disposition for every original range ID.
11. Final response returns an entry for every original canonical range using
    its original IDs/boundaries/summary/relevance, not a replacement group
    summary.

No group call may classify a record out of existence. `redundant` and
`not_material` remain visible dispositions.

## Loud visibility

When compaction triggers, all of the following are mandatory:

- WARNING structured event `ledger_compaction_required`;
- public stream event with exact budget measurements;
- visible Python-client progress text that says ledger compaction is running;
- continuously advancing elapsed time and heartbeats;
- per-group and per-level progress;
- temporary exact debug-capture records when capture is active;
- admin recent-events warning;
- admin since-process count of compacted requests;
- cumulative content-free usage/accounting for every compaction provider call;
- final `ledger_processing.compaction_applied=true`, level count, and group-call
  count;
- closeout/live-run report states whether compaction triggered.

Normal logs remain content-free. Persist only counts, operation identity,
tokens, timing, outcome, provider request ID, and cost.

## Debug capture additions

Extend current `DebugCaptureManager.record_for_request`; do not create a second
logger.

When active, record:

```text
retrieval_plan_generated
retrieval_query_embedding_metadata
retrieval_candidates_received
retrieval_candidate_fusion
retrieval_suggestion_ranges
retrieval_window_assignment
window_plan_details
ledger_synthesis_preflight
ledger_compaction_required
ledger_compaction_group_input
ledger_compaction_group_output
ledger_compaction_level_validation
retrieval_overlap_diagnostics
```

Existing `provider_request`, `provider_response`, provider errors, public
request, and public response capture remain authoritative for exact wire data.
Do not duplicate secrets; existing redaction rules remain.

## Practical expectation

Record the measured reference in admin help:

- a recent 40-range/558-evidence-message synthesis required 63,514 of 184,870
  usable input tokens and did not compact;
- compaction is therefore expected to be uncommon under current configuration,
  but remains available for broad or unusually long evidence ledgers and for
  smaller-context synthesis models.

This reference is explanatory text, not a threshold or behavioral cap.

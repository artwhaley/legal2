# Exhaustive Window Scan Recall Spec

## Goal
Make exhaustive window scan preserve valid evidence ranges and restore granular "all times" recall for broad legal-evidence questions.

The app must not silently discard valid evidence because a model supplied a bad range bracket, and it must not collapse materially distinct events into broad summary buckets when the user asks for every occurrence.

## Background
The production run on dataset 20 at `2026-07-01T08:27-08:36Z` used `z-ai/glm-5.1` and returned:

- 40 raw window ranges
- 38 validated window ranges
- 38 ledger records
- 38 final clickable ranges

The GLM 5.1 spike source file at `spikes/window_merge_lab/inputs/test.json` contains 6 window scans from model runs `165-170` and returned 67 ranges for the same school query.

The production run did not drop a large set during merge. The missing results were mostly not emitted by the window scan calls. Of the 67 spike hit IDs:

- 18 appeared as exact latest hit IDs
- 30 fell inside any latest accepted range
- 37 were absent from latest accepted ranges

The production prompt and larger 5-window packing encouraged broader clustering. The spike's 6-window shape and model behavior produced more granular ranges.

## Scope
This spec has three implementation tracks:

1. Repair valid hit-message ranges when only the start/end bracket is invalid.
2. Restore granular exhaustive window scan extraction for "all times" questions.
3. Add compact retrieval hints to exhaustive window scan calls without turning retrieval into a filter.

These tracks are related but independent. Do not use the range repair as a substitute for recall tuning.

## Product Contract
For exhaustive window scan:

- Every planned window is scanned exactly once unless the operation fails visibly.
- Every model-returned range is either accepted, repaired with an explicit reason, or rejected with an explicit reason.
- Valid evidence is not discarded merely because start/end bracketing is misordered.
- The scan prompt must favor materially distinct clickable evidence ranges over broad topic summaries.
- The merge step must receive all validated/repaired ranges deterministically.
- Merge must not reduce, rank, or suppress valid ledger records.

## Track 1: Hit-Only Repair For Misordered Ranges
When a model returns real in-window IDs but the range order is invalid, keep the evidence as a hit-only range instead of discarding it.

Eligible repair:

- `hit_message_id` is present.
- `hit_message_id` is valid for the current window.
- `hit_message_id`, `start_message_id`, and `end_message_id` are all in the same source thread if present.
- The only validation failure is range order or missing ordering for start/end.

Repair behavior:

- Set `start_message_id = hit_message_id`.
- Set `end_message_id = hit_message_id`.
- Preserve title, summary, display text, date description, and hit ID.
- Add an uncertainty or structured repair note stating that the model supplied an invalid bracket and the app repaired the range to hit-only.
- Log the original start/hit/end IDs and repair reason.

Do not repair:

- Unknown or invented hit IDs.
- Cross-thread ranges.
- Missing `hit_message_id`.
- Ranges whose hit ID is outside the scanned window.
- Non-dict or otherwise malformed range payloads.

## Track 2: Granular Exhaustive Scan Recall
The exhaustive scan prompt must make the scan call behave like an exhaustive evidence extractor, not a summarizer.

Change the window scan prompt to:

- Require one `answer_range` per materially distinct occurrence, event, decision, dispute, or logistics cluster.
- State that "all times" means high recall over compactness.
- Remove or soften wording that biases toward "fewer, better ranges."
- Explicitly allow many concise ranges when the window contains many distinct hits.
- Require broad summaries to be in `answer_summary`, not substituted for clickable ranges.
- Tell the model not to merge separate dates/incidents merely because they share a topic.

Window planning should remain budget-driven:

- Keep deterministic full coverage.
- Preserve overlap.
- Use the resolved usable input budget from the selected model/settings.
- Do not introduce a separate recall token cap without a measured follow-up decision.
- Do not reintroduce sessions.
- Do not add retrieval prefiltering to exhaustive scan.

The observed 5-window versus 6-window difference is a hypothesis to monitor, not a proven cause. The first recall fix is prompt hardening and visible accounting, not changing the token budget used for exhaustive scan planning.

## Track 3: Retrieval Hints For Exhaustive Window Scan
Use retrieval as an assistive signpost for each exhaustive window investigator. Retrieval must not replace the exhaustive scan, prefilter windows, or become the source of truth.

### Retrieval Contract
- Run retrieval once after exhaustive windows are planned and before per-window model calls.
- Retrieval hints are compact message/range IDs only. Do not include snippets, excerpts, summaries, or duplicated message text in prompts or normal logs.
- The per-window scan prompt already contains the full window text. Hints point the model back to messages it can read in that text.
- Per-window investigators receive only hints whose IDs fall inside that window.
- Hints are not answers. The model must inspect the full window and return all responsive ranges, including relevant ranges that are not hinted.
- Do not drop, skip, reprioritize, or shrink planned windows based on retrieval results.

### Retrieval Sources
- FTS5 hits for each planner-returned term.
- Broad message embedding hits for each planner-returned term.
- Broad chunk embedding hits for each planner-returned term.

The app must not Python-parse the user query into fallback search terms. If the planner fails, returns malformed JSON, or returns no valid terms, log that explicitly and run the exhaustive window scan without retrieval hints.

If an embedding index is not ready after valid planner terms were returned, log that the channel was unavailable and continue with the other hint channels. Do not pretend the unavailable channel ran.

### Search-Term Planner
The search-term planner only sees the user question. It does not see the corpus and must not infer corpus-specific names.

Prompt contract:

```text
You are planning literal keyword searches over a message corpus.

You only know the user's question. Do not invent names, institutions, events,
programs, people, or phrases that are not present in the user question.

Return 1-5 high-precision literal search terms or short phrases derived from
the user question.

Allowed:
- exact important words from the user question
- obvious morphology variants of those words
- very constrained ordinary-language variants only when likely source-message wording

Prefer precision over recall.
Avoid broad/common words likely to appear in unrelated conversations.
Avoid legal/task framing words unless they are likely to appear in source messages.
Return only JSON:
{"terms":["..."]}
```

For example, if the user asks about "school", the planner may return terms like `school`, `schools`, `homeschool`, `home school`, or `schoolwork`. It must not invent corpus-specific terms like school names, programs, teachers, or institutions unless the user used those words in the question.

Planner failure behavior:

- If the planner call fails, log the failure and run exhaustive scan without hints.
- If planner JSON is malformed, log the parse failure and run exhaustive scan without hints.
- If planner returns an empty valid term list, log `no_terms` and run exhaustive scan without hints.
- Do not silently degrade to raw-query tokenization.
- Do not search every word in the user's question.
- Do not reuse Simple Search's broader keyword expansion prompt for this path.

### Build Plan

#### New Run Type And Prompt
- Add a dedicated run type, for example `exhaustive_scan_retrieval_terms`.
- Add a dedicated task role if needed, or map it explicitly to the existing search-expansion role with separate logging that preserves the run type.
- Seed a default prompt matching the Search-Term Planner contract above.
- Keep this prompt separate from Simple Search keyword expansion. Simple Search can remain broader because users can remove chips; exhaustive scan hinting must remain precision-biased because it runs unattended inside the answer pipeline.

#### Data Model
Introduce small in-memory dataclasses or typed dicts in a new module, for example `message_evidence_workstation/search/exhaustive_hints.py`:

```python
@dataclass(frozen=True)
class ExhaustiveHintItem:
    source: Literal["fts5", "message_embedding", "chunk_embedding"]
    term: str
    source_thread_id: str
    hit_message_id: str
    start_message_id: str
    end_message_id: str

@dataclass(frozen=True)
class ExhaustiveHintBlock:
    source_thread_id: str
    start_message_id: str
    end_message_id: str
    hit_message_ids: tuple[str, ...]
    terms: tuple[str, ...]
    sources: tuple[str, ...]
```

Do not store snippets on these structures.

#### Pipeline Control Flow
In `run_exhaustive_window_scan_answer`, after windows are planned and before the per-window scan loop:

1. Call the retrieval-term planner LLM with only the user query.
2. Parse strict JSON `{"terms": [...]}`.
3. Clean terms only by trimming whitespace, deduping case-insensitively, and enforcing the 1-5 limit.
4. If planner fails, returns malformed JSON, or yields no valid terms:
   - log `exhaustive_scan_hint_planner_failed` or `exhaustive_scan_hint_planner_no_terms`;
   - set retrieval hints to empty;
   - continue the exhaustive window scan without hints.
5. If valid terms exist:
   - run FTS5 for each term;
   - run message embedding search for each term when the index is ready;
   - run chunk embedding search for each term when the index is ready;
   - normalize all hits into `ExhaustiveHintItem` values.
6. Deduplicate exact duplicate hint items.
7. Merge only overlapping or truly contiguous hint items in the same source thread.
8. Assign hint blocks to corresponding planned windows.
9. Pass only the assigned hint block IDs/ranges into that window's scan prompt.
10. Run every planned window exactly once regardless of hint count.

#### Retrieval Execution Details
- FTS5: use the existing FTS query path for the term. Record message hits as single-message hint items.
- Message embeddings: run broad message embedding search once per term. Record each hit as a single-message hint item.
- Chunk embeddings: run broad chunk embedding search once per term. Record each hit as a chunk/range hint item using `start_message_id` and `end_message_id` from `message_chunk`.
- If an embedding channel is unavailable because the index is not ready, log the unavailable channel and skip only that channel.
- If an embedding channel errors unexpectedly, fail the answer pipeline visibly unless the failure is explicitly classified as index-not-ready. Do not hide unexpected errors.

#### Deduplication And Contiguous Merge
- Deduplicate by `(source_thread_id, start_message_id, end_message_id, hit_message_id, source, term)`.
- Build message-order lookup from planned windows or indexed transcript ordering.
- Sort hint items by `(source_thread_id, start_order, end_order)`.
- Merge hint items only when:
  - same `source_thread_id`;
  - ranges overlap, or the next range starts exactly one message after the current range ends;
  - there is no unhinted message gap between them.
- Do not merge ranges separated by a one-message or two-message gap.
- Do not merge thematically similar but temporally separated hints.
- The merged block accumulates unique `hit_message_ids`, `terms`, and `sources`.

#### Window Assignment
- A hint block belongs to a window if the block's start/end range intersects that window's message IDs.
- If a block crosses a window boundary because of planned overlap, include the intersecting IDs/range in each relevant window.
- Preserve the original block identity in logs, but the prompt receives only IDs/ranges that exist in that specific window.

#### Prompt Injection Into Window Scan
Extend `build_exhaustive_window_scan_user_content` to accept `retrieval_hint_blocks`.

Append a compact hint section after window metadata and before or after transcript text:

```text
Retrieval hints for this window:
FTS/message/chunk hint ranges:
- decipher_message_1:6742
- decipher_export_19:3396..decipher_export_19:3397
```

The hint section must include the warning text from Hint Format. It must not include message snippets.

#### Logging Plan
Add process logs:

- `exhaustive_scan_hint_planner_started`
- `exhaustive_scan_hint_planner_completed`
- `exhaustive_scan_hint_planner_failed`
- `exhaustive_scan_hint_planner_no_terms`
- `exhaustive_scan_hint_retrieval_started`
- `exhaustive_scan_hint_retrieval_channel_completed`
- `exhaustive_scan_hint_retrieval_channel_unavailable`
- `exhaustive_scan_hint_blocks_built`
- `exhaustive_scan_hint_blocks_assigned`

Log details should include terms, counts, IDs, source names, and window IDs. Do not log snippets or message bodies.

#### Tests
Add focused tests for:

- planner success feeds exactly those terms into FTS/message embedding/chunk embedding;
- planner failure runs windows without hints and logs the failure;
- malformed planner JSON runs windows without hints and logs parse failure;
- empty planner terms run windows without hints and logs no-terms;
- no raw query token fallback occurs;
- hint prompt contains IDs/ranges only, no snippets;
- contiguous hint items merge;
- one-message gap hint items do not merge;
- temporally separated same-topic hits do not merge;
- hint blocks assign only to windows containing their IDs;
- unavailable embedding index logs channel unavailable without pretending success;
- unexpected embedding errors fail visibly.

#### Suggested Implementation Order
1. Add prompt/run type and parser tests.
2. Add hint item/block dataclasses and merge/assignment pure functions with unit tests.
3. Add retrieval executor with mocked FTS/embedding tests.
4. Wire hint collection into exhaustive window scan after planning.
5. Extend window prompt builder and prompt tests.
6. Add process logs and logging assertions.
7. Run focused conversational answer, retrieval, prompt, and FTS/embedding tests.

### Hint Format
The per-window prompt should use IDs only:

```text
Retrieval hints for this window:
FTS message_ids:
- decipher_message_1:6742
- decipher_message_1:6741

Message embedding message_ids:
- decipher_export_19:3396

Chunk embedding ranges:
- decipher_export_19:3396..decipher_export_19:3397
```

The prompt must state:

```text
Retrieval hints are not exhaustive and are not answers.
They identify messages that lexical/vector search considered potentially relevant.
Inspect the entire window. Return responsive ranges even if they are not listed as hints.
Do not ignore hinted messages unless they are clearly incidental or non-responsive.
```

### Hint Logging
Log IDs and counts, not snippets:

- Planner term list.
- FTS term hit counts.
- Message embedding hit count and message IDs.
- Chunk embedding hit count and chunk start/end IDs.
- Per-window hint counts by source.
- How many final answer ranges overlap retrieval hints.
- How many retrieval hints were not represented in final ranges.

Do not log 700 message snippets. If an audit export later needs text, make that an explicit separate export action.

## Logging Requirements
The following must be visible in process logs:

- Per-window raw range count.
- Per-window accepted range count.
- Per-window repaired range count.
- Per-window rejected range count.
- Per-window retrieval hint counts by source.
- Rejection reason counts.
- Repair reason counts.
- Retrieval planner terms and retrieval channel availability.
- Total raw, accepted, repaired, rejected counts before merge.
- Ledger entry count passed to merge.
- Final clickable answer range count.

Existing logging added around `exhaustive_window_scan_window_completed`, `exhaustive_window_scan_windows_completed`, and `evidence_ledger_built` should be extended, not replaced.

## Acceptance Criteria
- A model range with valid hit ID and misordered start/end is returned as a hit-only clickable answer range.
- The same repaired range is included in the evidence ledger passed to synthesis.
- Unknown hit IDs are still rejected.
- Cross-thread ranges are still rejected.
- Process logs distinguish repaired ranges from clean accepted ranges and hard rejected ranges.
- A regression fixture based on the two observed production failures verifies hit-only repair:
  - `decipher_message_1:5907` with invalid bracket `5962..5962`
  - `decipher_message_1:2118` with invalid bracket `2117..2111`
- Prompt tests assert the active exhaustive scan prompt no longer contains recall-hostile language such as "prefer fewer, better ranges" without an explicit "include all materially distinct evidence clusters" override.
- A mocked exhaustive scan with many distinct school events keeps each distinct returned range through ledger construction.
- Regression tests prove prompt hardening does not add a separate recall cap and scan planning still uses the resolved usable input budget.
- Exhaustive scan retrieval hints pass message IDs/ranges only, never snippets or duplicated message text.
- The search-term planner prompt states that it only knows the user question and must not invent corpus-specific names or institutions.
- Retrieval hint logs include counts and IDs only.

## Non-Goals
- No session coverage restoration.
- No semantic chunk boundary dependency.
- No merge-call ranking or deduplication.
- No retrieval prefiltering or hidden fallback to FTS/embeddings.
- No silent retry if a model under-recognizes relevant evidence.

## Handoff Notes
This spec is about preserving and exposing evidence. If implementation pressure appears to favor fewer calls, fewer ranges, or smoother answers, choose the more observable and complete path.

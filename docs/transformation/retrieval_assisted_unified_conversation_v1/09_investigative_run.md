# Investigative retrieval run

## Purpose

Measure whether semantic attention suggestions improve exhaustive recall and
whether models still find relevant evidence outside suggestions.

This is diagnostic, not a benchmark claiming statistical certainty.

## Fixed data and question

EVW:

```text
C:\Users\artwh\OneDrive\Documents\legal2\.tmp\sfv1-fixture-multicorpus-v15.evw
```

Large working-corpus revision:

```text
working_corpus_revision_id = 4
message_count = 12,402
```

Small one-window revision:

```text
working_corpus_revision_id = 3
```

The runner must verify IDs/readiness and report actual counts before calls; do
not silently choose another revision.

Exact question:

```text
When did we fight about school?
```

Do not change capitalization or wording between arms.

## Provisional known-positive ranges

These are a diagnostic seed from the successful six-window result, not a claim
that no other true positives exist:

| Event date | Thread | Start ID | End ID |
|---|---|---|---|
| 2023-03-28 | `julie_kramer` | `decipher_message_1:3572` | `decipher_message_1:3516` |
| 2023-11-13 | `julie_kramer` | `decipher_message_1:986` | `decipher_message_1:972` |
| 2024-06-26 | `julie_kramer` | `decipher_export_19:583` | `decipher_export_19:603` |
| 2024-07-10 | `julie_kramer` | `decipher_export_19:788` | `decipher_export_19:793` |
| 2025-07-16 | `julie_kramer` | `decipher_export_19:3370` | `decipher_export_19:3397` |
| 2025-08-04 | `julie_kramer` | `decipher_export_19:3451` | `decipher_export_19:3456` |
| 2026-07-01 | `julie_kramer` | `decipher_export_5:131` | `decipher_export_5:142` |

Resolve intervals by canonical thread ordinal, not lexical ID order. Fail if an
endpoint is absent or the range is reversed in corpus order.

## Runner interface

Implement subcommands:

```powershell
.\.venv\Scripts\python.exe scripts/run_retrieval_hint_experiment.py prepare `
  --evw ".tmp\sfv1-fixture-multicorpus-v15.evw" `
  --working-corpus-revision-id 4 `
  --server-url "http://127.0.0.1:8765" `
  --question "When did we fight about school?" `
  --output-dir ".tmp\retrieval-hint-experiment\<UTC-ID>"

.\.venv\Scripts\python.exe scripts/run_retrieval_hint_experiment.py run `
  --manifest ".tmp\retrieval-hint-experiment\<UTC-ID>\manifest.json" `
  --arm terms-only

.\.venv\Scripts\python.exe scripts/run_retrieval_hint_experiment.py run `
  --manifest ".tmp\retrieval-hint-experiment\<UTC-ID>\manifest.json" `
  --arm full-semantic

.\.venv\Scripts\python.exe scripts/run_retrieval_hint_experiment.py run `
  --manifest ".tmp\retrieval-hint-experiment\<UTC-ID>\manifest.json" `
  --arm censored-semantic

.\.venv\Scripts\python.exe scripts/run_retrieval_hint_experiment.py report `
  --manifest ".tmp\retrieval-hint-experiment\<UTC-ID>\manifest.json"
```

`prepare` performs exactly once:

1. read-only EVW validation;
2. retrieval-plan call;
3. one query-embedding workload;
4. all local per-query searches;
5. candidate-pool freeze;
6. provisional-gold rank analysis.

`run` never regenerates plan, vectors, or candidates.

The script checks `/admin/events` before every network phase and refuses unless
debug capture is active and writer status is healthy. Extend that existing
private admin projection with active config version and retrieval mode; do not
add a product/debug endpoint.

## Configuration preparation

Create two active-ready configuration versions through the existing admin
draft/activation flow:

- **T**: `retrieval_assistance_mode=terms_only`
- **S**: `retrieval_assistance_mode=semantic_ranges`

They must be clones differing only in that field. Verify their redacted
canonical config diff before the run.

Retrieval compatibility deliberately excludes assistance mode, so the frozen
plan from `prepare` remains valid in both.

Sequence:

1. Activate S and run `prepare`.
2. Activate T and run `terms-only`.
3. Activate S and run `full-semantic`.
4. If eligible, keep S active and run `censored-semantic`.
5. Run `report`.

Activation takes effect on the next request without restart. Record config
version for every arm.

The executor performs these admin actions. They are not user setup.

## Arm definitions

### Terms-only control

- Same frozen extracted queries.
- Analysis request contains the plan and `hits=[]`.
- Active server mode is `terms_only`.
- Window prompts contain literal queries and no suggestion ranges.

### Full semantic treatment

- Same frozen plan.
- Send every frozen raw candidate hit.
- Active mode is `semantic_ranges`.
- Server performs normal deterministic fusion/selection/range assignment.

### Censored semantic diagnostic

Run only if the full raw or selected semantic retrieval overlaps at least one
provisional positive.

Build the censored request from the frozen raw pool:

1. Remove every hit message whose corpus ordinal lies inside any provisional
   positive range.
2. Do not add an exclusion buffer.
3. Preserve the original pool in artifacts.
4. Re-rank each query's remaining hits contiguously from 1 in original order so
   the strict wire contract remains valid.
5. Send all remaining hits; normal server fusion backfills from lower-ranked
   non-positive candidates.
6. Require the shown suggestion count to equal the full arm when enough
   candidates exist.
7. If insufficient candidates exist, use all remaining candidates and report
   the count difference; never fabricate noise.
8. Assert no shown suggestion overlaps a provisional positive.
9. Report the nearest remaining suggestion's ordinal distance from every
   omitted positive.

## Comparison validity

The report must refuse an apples-to-apples quality conclusion unless:

- question is byte-identical;
- retrieval-plan ID/fingerprint/query list is identical;
- embedding artifact/geometry is identical;
- redacted configurations differ only in assistance mode;
- extraction, compaction, and synthesis model profiles/prompts are identical;
- window-plan hash and ordered boundaries are identical;
- no arm returned partial/failed output.

If invalid, preserve all artifacts and state exactly why.

## Metrics

For retrieval itself:

- best raw rank per provisional event and query;
- whether any event appears in selected shown suggestions;
- query/queries that retrieved it;
- selected versus raw-only;
- suggestion count and distribution per window.

For each arm:

- final range and disposition inventory;
- provisional event recall;
- final ranges overlapping suggestions;
- final ranges outside all suggestions;
- `used` ranges inside/outside suggestions;
- novel apparently relevant ranges outside the provisional set;
- suggestions producing no evidence;
- input/output tokens by operation;
- provider attempts/retries;
- wall time and per-window time;
- ledger direct input/usable tokens;
- compaction applied/levels/groups;
- exact strategy and window-plan hash.

For censored versus full:

- which omitted positives were still independently found;
- which were lost;
- whether unrelated noise increased false positives or overcollection;
- whether outside-suggestion recall changed.

Do not reduce the result to one numeric score. Produce a table plus exact range
IDs for human review.

## Artifacts

Write:

```text
.tmp/retrieval-hint-experiment/<UTC-ID>/
  manifest.json
  provisional-gold.json
  retrieval-plan.json
  query-embedding-metadata.json
  raw-candidates.json
  raw-gold-overlap.json
  terms-only-request.json
  terms-only-result.json
  full-semantic-request.json
  full-semantic-result.json
  full-selected-suggestions.json
  censored-candidates.json
  censored-semantic-request.json
  censored-semantic-result.json
  censored-selected-suggestions.json
  comparison.json
  comparison.md
```

Do not write vectors or duplicate full corpus text to these artifacts. Exact
wire/provider content is already in server debug capture.

Use atomic file replacement for each artifact and record SHA-256 hashes in the
manifest.

## Logging lifecycle

Before `prepare`, start a fresh debug capture from `/admin/debug`. Keep it
active through all configuration activations and arms. After `report`:

1. stop accepting new captured requests;
2. wait for all bound requests to finish;
3. wait for pending writer records to reach zero;
4. record exact capture session ID/path/size;
5. do not delete the capture.

The capture contains private corpus content and remains temporary server-side
development data.

## Cost discipline

- One retrieval-plan call.
- One query-embedding workload.
- One 100K smoke conversation.
- One terms-only large conversation.
- One full-semantic large conversation.
- One censored large conversation only when eligible.
- Configured retries only.
- No automatic repetitions.

If a model/provider fails, preserve the run and stop that arm after configured
behavior. Do not silently switch provider or model.


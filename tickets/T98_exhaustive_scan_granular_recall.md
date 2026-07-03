# T98 - Exhaustive Scan Granular Recall

## Goal
Restore high-recall, granular exhaustive window scan behavior for "all times" questions.

## Background
The GLM 5.1 spike source windows in `spikes/window_merge_lab/inputs/test.json` returned 67 ranges for:

```text
Show me all the times we talked about school
```

The latest production GLM 5.1 run returned 40 raw ranges and 38 final clickable ranges for the same question. Merge did not collapse a large number of ranges; the missing results were mostly not emitted by the initial window scans.

Measured comparison:

- 67 spike hit IDs total
- 18 exact latest hit matches
- 30 spike hits inside any latest accepted range
- 37 spike hits absent from latest accepted ranges

The latest run used 5 larger windows. The spike used 6 smaller windows. That difference is worth monitoring, but it is not proven to be the root cause. The current prompt also says "Prefer fewer, better ranges", which biases the model toward broad clusters instead of exhaustive clickable hits.

**Spec reference:** `09_exhaustive_window_scan_recall_spec.md` Track 2

## Scope
Update exhaustive window scan prompting and measurement so the scan stage emits materially distinct ranges without changing the resolved scan token budget.

Primary files likely include:

- `message_evidence_workstation/nim/prompts.py`
- prompt migration/seed code if prompts are stored in DB fixtures
- `message_evidence_workstation/search/window_planner.py`
- `message_evidence_workstation/search/conversational_answer.py`
- relevant settings/tests

## Prompt Changes
Revise the active `exhaustive_window_scan` prompt.

Required behavior:

- The scan call is an evidence extractor, not a summarizer.
- For "all times", "every time", or similarly broad requests, favor recall over compactness.
- Return one `answer_range` per materially distinct occurrence, event, dispute, decision, scheduling/logistics issue, illness/absence, school option, curriculum discussion, payment/tuition issue, or other separate evidence cluster.
- Do not merge separate dates/incidents just because they share the same topic.
- Keep each range concise and contiguous.
- Use `answer_summary` for the broad overview; do not substitute the overview for clickable ranges.

Remove or rewrite:

```text
Prefer fewer, better ranges over bloated duplicate ranges
```

Acceptable replacement:

```text
Prefer concise, non-duplicative ranges, but include every materially distinct evidence cluster. For "all times" questions, high recall is more important than minimizing the number of ranges.
```

## Window Planning Contract
Do not add a separate recall-oriented scan window cap in this ticket.

Requirements:

- Keep full deterministic coverage.
- Keep configured overlap.
- Use the resolved usable input budget from model/settings.
- Do not reintroduce sessions.
- Do not use retrieval, FTS, or embeddings as a filter for exhaustive scan.

Logging:

- `exhaustive_scan_preflight` includes:
  - `per_call_input_budget`
  - `planned_window_count`
  - `window_overlap_messages`
- Per-window scan logs already include raw, validated, repaired, and rejected range counts. Preserve or extend those logs.

## Acceptance Criteria
- Active exhaustive scan prompt no longer contains recall-hostile "fewer ranges" language without a high-recall override.
- Prompt tests verify "all times" questions are instructed to return one range per materially distinct occurrence.
- Exhaustive scan planning still passes `budget.usable_input_tokens` to `build_token_bounded_windows_for_dataset`.
- No `scan_window_target_tokens`, `planning_reason=recall_cap`, or equivalent separate recall cap is introduced.
- Existing exhaustive scan merge path still receives all accepted/repaired ranges deterministically.
- No retrieval prefiltering is added.
- No session logic is added back.

## Tests
- Prompt snapshot or string test for the active exhaustive scan prompt.
- Integration test that `run_exhaustive_window_scan_answer` uses the resolved input budget for planned windows.
- Regression test with mocked window scan responses containing many distinct ranges; assert ledger entry count equals all ranges.
- Run:
  ```text
  python -m pytest tests/test_conversational_answer.py tests/test_window_planner.py tests/test_prompts_model_runs.py -q
  ```

## Guardrails
- Do not tune this by hiding results in merge.
- Do not deduplicate unless exact duplicate range IDs or identical hit IDs are present and the behavior is explicit.
- Do not optimize for fewer API calls at the cost of recall.
- Do not silently change behavior based on model provider.

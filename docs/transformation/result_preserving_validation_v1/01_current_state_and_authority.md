# Current state and authority

## Observed current implementation

The current server path is:

```text
analysis planning
-> optional local semantic suggestions
-> exhaustive one/many-window extraction
-> per-range source validation
-> deterministic ledger
-> optional ledger compaction
-> ledger synthesis
-> all-or-nothing synthesis validation
-> completed result or failed event
```

The planning, exhaustive coverage, range-granular source validation, and
canonical ledger are valuable and remain.

The destructive defect is after synthesis:

- `LedgerSynthesisOutput` requires one exact JSON shape.
- `range_dispositions` must form an ordered bijection over every ledger range.
- findings are rejected unless they cite a range separately labeled
  `direct_evidence`.
- any synthesis semantic mismatch raises `LedgerError`.
- nearly every `LedgerError` maps to `LEDGER_BIJECTION_FAILED`.
- the public stream returns only `failed`; the readable answer survives only
  in temporary debug capture.
- model-output/schema failures are not eligible for configured provider
  retries.

One real GLM 5.2 run on 2026-07-30 completed planning, nine extraction windows,
and synthesis. It returned a readable 21-result answer and all 21 exact range
IDs. The server discarded it because three ranges labeled `useful_context`
also appeared as standalone findings. The public error falsely claimed a
ledger bijection failure.

Review artifact:

`.tmp/question-planned-analysis-live/20260730T161644Z-bacdd272/live-run-review.md`

The executor may use that artifact for local diagnosis if present, but tests
must use synthetic data and must not depend on `.tmp` or private transcript
content.

## Current contact surfaces

At packet creation, active contacts include:

- `server/contracts.py`
- `server/prompts.py`
- `server/model_runtime.py`
- `server/evidence_ledger.py`
- `server/conversation_unified.py`
- `server/observability.py`
- `server/admin.py`
- `server/token_accounting.py`
- `server/resilience.py`
- `message_evidence_workstation/client_api/contracts.py`
- `message_evidence_workstation/client_api/gateway.py`
- `message_evidence_workstation/services/client_workflows.py`
- `message_evidence_workstation/ui/main_window.py`
- `scripts/run_question_planned_analysis_live.py`
- `scripts/run_retrieval_hint_experiment.py`
- `tests/sfv1_support.py`
- QPA1/SFV1 conversation, contract, synthesis, resilience, admin, client,
  mixed-load, and experiment tests

The executor must inventory again before editing. This repository has a large
dirty worktree containing intentional user/agent work. Preserve it.

## Authority

This packet deliberately breaks the current synthesis/result contract. Do not
preserve backward compatibility for:

- `Disposition`
- `RangeDisposition`
- `range_dispositions`
- `direct_evidence`
- `useful_context`
- `not_responsive`
- direct-evidence-required findings
- ordered-disposition bijection as a publication gate
- `partial_evidence_validation`
- `LEDGER_BIJECTION_FAILED` as a generic ledger error
- synthesis format failure as a terminal loss of readable output

Delete or rewrite conflicting old tests. Do not retain aliases or dual runtime
paths to keep obsolete tests green.

This packet does not authorize changes to:

- EVW schema or lifecycle;
- Flutter;
- local vector persistence or lookup algorithms;
- authentication, billing, Clerk, Stripe, or BYOK;
- route count or route names;
- frozen planner architecture;
- server EVW access;
- provider ownership by clients;
- server-side corpus persistence.


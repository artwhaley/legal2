# Acceptance gates

The executor performs dependency repair, tests, process control, fixture
preparation, and live execution. Do not assign automated work to the user.

Use only:

```powershell
.\.venv\Scripts\python.exe
```

Do not install into or reason from system Python. Routine tests use
deterministic fakes, make no real model calls, and do not rebuild large
embeddings.

## Gate A - Baseline and boundaries

- complete dirty-worktree/process/config/route inventory;
- compile baseline;
- focused/full test baseline;
- package-boundary baseline;
- `git diff --check`;
- no mutation before inventory.

## Gate B - Contracts and prompt migration

- new synthesis and public result contracts;
- exact status/answer-source/citation/warning/event invariants;
- old dispositions and status rejected;
- long answer accepted;
- known default prompt migrated;
- custom incompatible prompt rejected with clear action;
- settings/secrets/version identity preserved;
- restart and rollback proven.

## Gate C - Result-preserving synthesis inspection

- conforming output completes;
- readable malformed output completes with warnings;
- GLM-shaped classification contradiction completes with warnings;
- high/lower ordering;
- mixed valid/fabricated citation salvage;
- all-fabricated isolation;
- omitted ranges preserved;
- unclassified results preserved;
- no heuristic rewriting;
- no fabricated verified link.

## Gate D - Range source integrity

- valid sibling ranges survive;
- source thread derived/corrected safely;
- endpoint reversal corrected safely;
- unknown/cross-thread/ambiguous ranges quarantined;
- all-invalid parseable window remains usable;
- unusable top-level output is distinguished;
- exact debug capture and content-free normal logs.

## Gate E - Window isolation and retries

- targeted retry repeats only failed window;
- exhausted window returns partial with siblings;
- sibling failure does not cancel completed work;
- deterministic range IDs under concurrency;
- exact coverage report;
- all unavailable windows hard-fail only after attempts;
- cancellation and accounting remain exact.

## Gate F - Synthesis and compaction preservation

- synthesis receipt event precedes validation;
- readable response cannot become failed;
- empty synthesis retries only synthesis;
- exhausted synthesis returns ledger-only partial;
- compaction failure preserves canonical ledger;
- overflow after compaction failure returns ledger-only partial;
- no hidden model/provider fallback;
- all usage retained.

## Gate G - Prompts, admin, and observability

- prompts implement overcollection and high/lower presentation;
- no obsolete disposition language;
- admin explains behavior and shows exact schema;
- settings affect next request without restart;
- warning/partial metrics are real;
- logs/accounting are content-free;
- debug capture remains explicit and temporary.

## Gate H - Python test equipment and runners

- strict new contracts;
- visible high/lower divider;
- lower/unclassified material never hidden;
- warnings/partial outcomes are successful;
- fabricated IDs cannot navigate;
- raw answer and ledger-only fallback render;
- progress/timer remain correct;
- visible-history persistence only;
- no automatic expensive rerun.

## Gate I - Full regression and mixed load

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Run explicit deselected scale/browser/mixed-load tests.

Then:

```powershell
.\.venv\Scripts\python.exe -m compileall -q server message_evidence_workstation scripts tests
.\.venv\Scripts\python.exe scripts\verify_package_boundaries.py
git diff --check
```

Prove no real API calls or large embedding rebuilds occurred in automated
tests.

## Gate J - Forbidden residue

Active runtime, Python client, scripts, and current tests contain none of:

```text
direct_evidence
useful_context
not_responsive
range_dispositions
validate_dispositions
validate_findings
partial_evidence_validation
LEDGER_BIJECTION_FAILED
```

Historical packet documents and explicit migration-input fixtures are allowed.
There is one active result path and one active synthesis schema.

## Gate K - Live proof

Only after Gates A-J pass, execute file 10.

## Final gate

Completion requires:

- RPV1-000 through RPV1-900 dispositioned;
- all local gates green;
- one live returned answer or exact external blocker;
- execution log and closeout report;
- no known in-scope defect;
- server/debug/config/process cleanup;
- lean manual test instructions.


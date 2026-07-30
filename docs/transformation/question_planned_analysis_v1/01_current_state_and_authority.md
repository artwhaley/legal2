# Current state and authority

## State observed when this packet was written

The repository currently has:

- configuration schema v3;
- five model operations:
  `keyword_expansion`, `retrieval_terms`, `window_evidence_extraction`,
  `ledger_compaction`, and `ledger_synthesis`;
- four product routes, including
  `/v1/conversational-retrieval-plan`;
- a shallow `retrieval_terms` model output containing only `terms`;
- local client-side message-vector lookup and server-side RRF suggestion
  construction;
- deterministic one/many-window planning and one canonical ledger path;
- strict whole-window rejection when any extracted range has invalid identity,
  thread binding, or endpoint order;
- synthesis dispositions `used`, `redundant`, and `not_material`;
- a synthesis prompt that globally asks the model to account for
  contradictions and absence, whether or not the user asked;
- a compaction output that prematurely emits range dispositions;
- a server-rendered admin with reusable provider/model profiles, per-operation
  prompt/model controls, active/draft activation, debug capture, accounting,
  and next-request configuration behavior;
- a Python client workflow that performs retrieval planning, query embeddings,
  local lookup, and conversational analysis as test equipment.

The unified one/many-window architecture, local vector boundary, compaction
fallback, concurrency, cancellation, retry runtime, accounting, and debug
capture are working foundations. Extend them; do not replace them.

## Known live evidence motivating this packet

The preserved six-window comparison under:

`.tmp/six-window-model-comparison/20260730T031230Z`

showed:

- GLM 5.2 with the frozen planning addition completed 6/6 strict windows,
  returned 41 candidate ranges, and overlapped 7/7 provisional positives;
- Nemotron completed 6/6 strict windows, returned 20 ranges, and overlapped
  6/7;
- MiniMax returned several useful ranges but one window timed out and another
  response contained three valid ranges plus one fabricated message ID, causing
  the current validator to reject the whole window.

These are diagnostic artifacts, not production fixtures. Do not copy private
corpus content into committed tests or documentation.

## Authority rules

Where requirements conflict:

1. repository `AGENTS.md` controls implementation discipline;
2. this packet controls planning, endpoint naming, v4 contracts, extraction
   validation, dispositions, prompts, admin changes, and proof;
3. `retrieval_assisted_unified_conversation_v1` controls unchanged local
   retrieval, RRF, window packing, compaction, and server/client boundaries;
4. older packets are historical only.

Do not preserve v3 API names, operation names, result fields, modes, or
disposition literals for compatibility. Perform one explicit migration and
leave one v4 runtime path.

## Worktree warning

The worktree is heavily dirty and contains the in-progress server/client
transformation plus numerous `.tmp` artifacts. These changes belong to the
user.

The executor must:

- inventory status before editing;
- never reset, clean, checkout, or rewrite unrelated changes;
- avoid touching deleted legacy Python-client modules;
- keep packet work narrowly inside current server, current client gateway/
  workflow, tests, scripts, and this documentation folder;
- record overlapping edits before modifying a dirty file.

## Baseline requirement

QPA1-000 records the actual execution-time branch, HEAD, upstream relationship,
dirty files, route inventory, config schema, operation inventory, active
configuration with secrets redacted, debug-capture state, relevant deterministic
test results, and current provider processes.

Do not assume the historical closeout count is still current.


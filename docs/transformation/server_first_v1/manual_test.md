# Manual acceptance test

Automated tests, dependency setup, fixture construction, and native probes are
executor-owned gates and are already complete. This checklist contains only
behavior that requires a person to inspect the real interfaces or intentionally
authorize paid model calls.

## Prepared file and addresses

- Server admin: `http://127.0.0.1:8710/admin/`
- V15 EVW: `C:\Users\artwh\OneDrive\Documents\legal2\.tmp\sfv1-fixture-multicorpus-v15.evw`
- Flutter release viewer: `C:\Users\artwh\OneDrive\Documents\legal2\flutter_client\build\windows\x64\runner\Release\evw_client.exe`
- Python harness interpreter: `C:\Users\artwh\OneDrive\Documents\legal2\.venv\Scripts\python.exe`

The one V15 EVW contains the 15,462-message source dataset and both ready test
scopes:

- `Recent ~700K Tokens`, revision 2: 12,402 messages and 698,786 stored
  membership tokens. The server selects the windowed-ledger path.
- `Recent ~100K Tokens (Whole-Corpus Test)`, revision 1: 1,387 messages and
  99,980 stored membership tokens. The server selects the whole-corpus path.

These are independent immutable working-corpus revisions in one EVW. Do not
copy or switch EVW files to switch scopes. Flutter and the Python harness take
an exclusive EVW writer lock, so close one before opening the EVW in the other.

## 1. Admin web interface

Open the admin address. Authentication is intentionally not present in this
phase; the admin listener is loopback-only. Do not expose port 8710 publicly.

Confirm that the page shows:

- active immutable configuration version 2 and a separate editable draft;
- listener `127.0.0.1:8710`;
- all six internal operations:
  `keyword_expansion`, `retrieval_terms`, `whole_corpus_answer`,
  `window_evidence_extraction`, `ledger_reduction`, and `ledger_synthesis`;
- for every operation, the provider URL, model, full editable system prompt,
  token budgets, timeout, retry, concurrency and circuit controls, exact
  response schema, and generated provider-payload preview;
- the local embedding model, artifact/profile identity, dimensions, worker and
  queue state, throughput, batch sizing, timeouts, and request limits;
- durable usage totals, version history, audit history, provider circuits,
  queues, config-database WAL state, and recent redacted events.

Saving edits must update only the draft. Validate the draft, then Activate to
create a new immutable active version. A config or secret save must be all-or-
nothing: a visible failure must not leave only part of the draft changed.

The per-operation test buttons make real provider calls and can cost money.
Use them only when intentionally validating the configured provider. A failure
must stay visible with its operation, provider status, and safe error details;
it must not switch providers/models or pretend success.

## 2. Flutter V15 viewer

Run:

```powershell
& 'C:\Users\artwh\OneDrive\Documents\legal2\flutter_client\build\windows\x64\runner\Release\evw_client.exe' `
  --evw 'C:\Users\artwh\OneDrive\Documents\legal2\.tmp\sfv1-fixture-multicorpus-v15.evw'
```

Confirm that the viewer opens the V15 EVW, reports 15,462 source messages, and
lists both ready working-corpus revisions above. Select each revision and
confirm its message/token counts. Page the transcript and confirm visible
messages are populated and change with the selected scope. Close Flutter before
opening the Python harness.

## 3. Python harness: local search and embeddings

Launch the prepared EVW with the project virtual environment:

```powershell
& 'C:\Users\artwh\OneDrive\Documents\legal2\.venv\Scripts\python.exe' `
  -m message_evidence_workstation.app `
  --db 'C:\Users\artwh\OneDrive\Documents\legal2\.tmp\sfv1-fixture-multicorpus-v15.evw'
```

Select `Recent ~700K Tokens · revision 2 · ready`. The scope line must show
12,402 messages and approximately 698,786 tokens. Then:

1. Enter `school` and click **FTS5**. Results must be local, non-empty, and
   limited to the selected revision.
2. Enter `school meeting` and click **Keyword**. The server performs the
   expansion call; the displayed search hits are produced by local,
   revision-scoped FTS5.
3. Click **Build / refresh local embeddings**. This means every message in the
   selected working corpus, not every message in the source dataset. Progress
   must update for real server batches through completion. Existing vectors are
   reused by content hash; only missing vectors are requested and persisted.
   A real failure must remain visible. There is no fixed whole-job HTTP timeout.
4. Enter `school` and click **Embedding**. The server embeds only that query;
   vector lookup and displayed messages remain local and revision-scoped.

The server currently uses a local embedding backend, but the client contract is
only `POST /v1/embeddings`. Replacing the server backend with an external
provider later does not change this client workflow.

## 4. Windowed conversational path

Keep the 700K revision selected. Enter a concrete question and click
**Conversational**.

The client sends one question and the complete selected working corpus. It does
not choose a model, context strategy, window size, prompt, provider batch size,
retry policy, or synthesis behavior. Confirm:

- visible progress advances through retrieval, window extraction, ledger
  reduction, and synthesis;
- the completed result reports `strategy: "windowed_ledger"`;
- coverage reports all 12,402 source message IDs with no omissions;
- the result includes `answer`, `answer_summary`, `evidence_ledger`,
  `uncertainties`, `coverage`, and `usage`;
- failures remain terminal and visible; only a completed result is stored in
  the EVW.

Under active version 2, this fixture is currently planned into eight windows.
That number may change when an operator intentionally changes model context or
window-budget settings; the required behavior is complete coverage, not a
hard-coded window count.

## 5. Whole-corpus conversational path

In the same running Python harness and the same EVW, select
`Recent ~100K Tokens (Whole-Corpus Test) · revision 1 · ready`. Confirm the
scope line shows 1,387 messages and approximately 99,980 tokens.

Enter a concrete question and click **Conversational**. Confirm:

- the completed result reports `strategy: "whole_corpus"`;
- coverage reports all 1,387 source message IDs;
- no window-extraction or ledger-reduction calls occur;
- the normal retrieval-terms operation may precede the single
  whole-corpus-answer operation;
- the same strict final result fields are present.

Switch back to the 700K revision and confirm the harness immediately restores
that revision's independent FTS/vector/conversational scope. Close the harness
normally when finished so the EVW is checkpointed and its exclusive lock is
released.

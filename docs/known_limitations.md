# Known Limitations (MVP)



## Data import



- Loader expects a **directory** with `dataset.json`, `source_threads.jsonl`, and `messages.jsonl`.

- Single merged JSON files (e.g. `julie_kramer_merged_normalized.json`) are not imported directly yet.

- Import uses streaming JSONL with batched inserts; peak memory is bounded by batch size, not total message count.



## SQLite and concurrency



- SQLite is single-writer: only one embedding index build should run at a time per workspace database.

- Background workers use separate connections with WAL mode; UI reads share the same database file.

- Concurrent embedding builds or multiple writers are unsupported and may corrupt index state.



## Search and embeddings

- Simple Search uses explicit modes (FTS5, expanded keyword, message embedding, chunk embedding). Search runs on **Search** or **Enter** only; typing does not query the database.
- FTS5 and expanded keyword modes page at SQL level with honest total counts. Embedding modes return top-K similarity results only.
- Background search workers use separate SQLite connections; **Cancel** suppresses stale result rendering.
- Transcript scrolling uses per-thread `thread_ordinal` indexed access instead of OFFSET/ROW_NUMBER scans.

- Scale / large-fixture regression tests are marked `@pytest.mark.scale` and excluded from the default fast suite. Run manually: `python -m pytest -m scale -q`.

- Embedding builds are slow on large datasets; chunk builds stream per thread but still take time.

- Embedding vectors are stored per model in the workspace `.evw` file (sqlite-vec `model_name` partition key). Switching back to a previously built model reuses cached vectors when dimensions match. Models with different vector dimensions cannot share the same vec table — changing dimensions drops and recreates the vec virtual table.

- The app does not restore a loaded dataset in the UI on reopen; use **Home → Load Dataset** each session (CLI `--dataset` auto-run still works).

- sqlite-vec KNN filters by dataset in Python after oversampling (vec0 constraint).

- Keyword expansion and conversational features require a configured NVIDIA NIM model and API key.



## Transcript widgets

- **Transcript Widget** (legacy) uses the virtualized Gen2 surface. **New Transcript Widget** is a parallel document-backed demonstrator (`QTextDocument`). **Virtual Transcript Widget** is the Gen 3 paint-based virtual layout path intended to replace Gen 1 at scale.
- Simple Search and Conversational Interface still use the legacy **Transcript Widget** only. New and Virtual tabs are demonstrators.
- New Transcript Widget materializes the active thread into a document cache (batched SQL fetch). Very large single threads may take time to build; jump navigation is direct via scrollbar positioning, not row virtualization.
- Virtual Transcript Widget loads message bodies only for the visible ordinal window plus overscan. Variable-height layout uses a prefix-sum height index; boundary/hit/highlight controls are repainted from slot ordinals (no pixel persistence).
- Scale validation: `python -m pytest tests/test_new_transcript_widget.py -m scale -q` and `python -m pytest tests/test_virtual_transcript_widget.py -q`.
- Virtual widget is ready for manual 15k-message testing but **not yet wired** into Simple Search or Conversational workflows.

## Conversational interface



- Planner is advisory only; Python always runs the full retrieval harness.

- Synthesis and range suggestion trust NIM JSON output; malformed responses fall back or surface errors.

- **Whole-transcript mode** still loads and serializes the full dataset when selected; it is only viable when SQL budget stats fit the configured context window. Use exhaustive window scan for large datasets.

- **Session-coverage** (`session_coverage` answer strategy) is a legacy research-model path with lower recall than exhaustive scan; prefer exhaustive scan for donor-scale review.



## Output formatting



- Boundary controls use **set-to-selected-message** buttons, not draggable handles.

- Print preview uses the real layout engine; use the preview widget's print/PDF action for export (not court-ready filing templates).

- No exhibit numbering or filing templates.



## Audit



- ModelRun logs may contain message snippets from NIM inputs; no redaction layer.

- Process log export is capped (default 5000 entries per export call).



## Platform



- Desktop MVP targets Windows dev environment; PySide6 + PyTorch embedding loads must stay on a consistent worker thread.

- pytest temp-dir cleanup may warn on Windows (`PermissionError`) without failing tests.

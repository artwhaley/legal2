# Known Limitations (MVP)

## Data import

- Loader expects a **directory** with `dataset.json`, `source_threads.jsonl`, and `messages.jsonl`.
- Single merged JSON files (e.g. `julie_kramer_merged_normalized.json`) are not imported directly yet.

## Search and embeddings

- Embedding builds are slow on large datasets; chunk builds stream per thread but still take time.
- sqlite-vec KNN filters by dataset in Python after oversampling (vec0 constraint).
- Keyword expansion and conversational features require a configured NVIDIA NIM model and API key.

## Conversational interface

- Planner is advisory only; Python always runs the full retrieval harness.
- Synthesis and range suggestion trust NIM JSON output; malformed responses fall back or surface errors.

## Output formatting

- Boundary controls use **set-to-selected-message** buttons, not draggable handles.
- HTML preview is printable HTML in the browser, not court-ready PDF/DOCX.
- No exhibit numbering or filing templates.

## Audit

- ModelRun logs may contain message snippets from NIM inputs; no redaction layer.
- Process log export is capped (default 5000 entries per export call).

## Platform

- Desktop MVP targets Windows dev environment; PySide6 + PyTorch embedding loads must stay on a consistent worker thread.
- pytest temp-dir cleanup may warn on Windows (`PermissionError`) without failing tests.

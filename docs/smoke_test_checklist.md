# Message Evidence Workstation — Smoke Test Checklist

Use the sample dataset in `tests/fixtures/sample_dataset` unless you have a prepared normalized donor directory.

## Setup

- [ ] Create venv and `pip install -e ".[dev]"`
- [ ] `pytest` passes
- [ ] `python -m message_evidence_workstation.app` launches

## Dataset

- [ ] App loads sample dataset (or use `--reload-dataset` with configured default path)
- [ ] Sidebar shows source threads and empty categories
- [ ] Source Thread Viewer opens a thread

## Categories and conversations

- [ ] Create a category from sidebar `+`
- [ ] Simple Search finds `allergy` hits
- [ ] Drag a grouped result into a category
- [ ] Workstation conversation appears under category

## NIM (requires API key + model in Setup / Settings)

- [ ] Keyword expansion returns yellow chips / expanded hits
- [ ] Conversational Interface returns answer + candidates after harness + synthesis
- [ ] Add a synthesis candidate to a category

## Embeddings (optional if local model installed)

- [ ] Embedding model shows **Ready** in Settings
- [ ] Validate sqlite-vec succeeds
- [ ] Build message embeddings (resume/skip if already complete)
- [ ] Purple/pink vector search returns hits in Simple Search

## Output formatting

- [ ] Open Output Formatting tab, select category + conversation
- [ ] Range suggestion runs on first open (or use Re-run range suggestion)
- [ ] Adjust a boundary using selected message + boundary button
- [ ] Apply highlight override on a message
- [ ] Preview HTML opens in browser
- [ ] Save HTML writes a file

## Audit

- [ ] Settings → export process log JSON/text
- [ ] Settings → ModelRun list shows planner/synthesis/range runs after NIM use
- [ ] Export audit bundle writes `process_log.json`, `process_log.txt`, `model_runs.json`

## Failure visibility

- [ ] Induce a NIM failure (bad key) — error visible in status, live log, and ModelRun viewer

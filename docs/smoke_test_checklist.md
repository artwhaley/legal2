# Message Evidence Workstation — Smoke Test Checklist

Use the sample dataset in `tests/fixtures/sample_dataset` unless you have a prepared normalized donor directory.

## Setup

- [ ] Create venv and `pip install -e ".[dev]"`
- [ ] `pytest` passes
- [ ] `python -m message_evidence_workstation.app` launches

## Dataset

- [ ] App loads sample dataset (or use `--reload-dataset` with configured default path)
- [ ] Sidebar shows source threads and evidence block categories
- [ ] Selecting a source thread opens the Transcript Widget tab

## Evidence blocks

- [ ] Create a category from sidebar `+`
- [ ] Simple Search finds `allergy` hits
- [ ] Drag a grouped result into a category (creates an evidence block)

## NIM (requires API key + model in Setup / Settings)

- [ ] Keyword expansion returns yellow chips / expanded hits
- [ ] Conversational whole-transcript answer completes
- [ ] Conversational exhaustive window scan completes
- [ ] Conversational session-coverage answer completes (research-model prep + final answer)
- [ ] Add a synthesis candidate to a category (legacy harness tests only)

## Model router (T28–T32)

### NIM-only (all roles on NIM)

- [ ] Settings → Model routing shows Expansion / Research / Writing controls
- [ ] Per-role **Test** buttons succeed for each role
- [ ] **Refresh model list** still populates the legacy NIM model combo
- [ ] Whole-transcript, windowed scan, and session-coverage answers work
- [ ] ModelRun rows show `provider=nim` and `_router_audit.task_role`

### Mixed NIM + Google (after configuring Google API key)

- [ ] Set Research (or Writing) to Google + manual model (e.g. `gemini-2.0-flash`)
- [ ] Session-coverage mode uses Google for summaries/classify/audit when Research is Google
- [ ] Expansion keyword search still uses NIM when Expansion is NIM
- [ ] ModelRun rows show correct per-call `provider`

### Failure cases

- [ ] Missing NIM key — actionable error in status + ModelRun
- [ ] Missing Google key — actionable error when a Google-backed role is invoked
- [ ] Bad model name — test button and workflow surface clear failure
- [ ] Restart app — per-role provider/model assignments persist

## Embeddings (optional if local model installed)

- [ ] Embedding model shows **Ready** in Settings
- [ ] Validate sqlite-vec succeeds
- [ ] Build message embeddings (resume/skip if already complete)
- [ ] Purple/pink vector search returns hits in Simple Search

## Output formatting

- [ ] Open Output Formatting tab; default printable artifact group is visible
- [ ] Drag an evidence block onto a group to create a printable artifact
- [ ] Drag another evidence block onto the artifact to append it
- [ ] Edit title, exhibit number, and case number; Save metadata
- [ ] Move blocks up/down and remove an included block
- [ ] Preview shows paged content with footer and end-of-artifact provenance ledger

## Audit

- [ ] Settings → export process log JSON/text
- [ ] Settings → ModelRun list shows routed runs after model use (check `provider` + `task_role` in raw JSON)
- [ ] Export audit bundle writes `process_log.json`, `process_log.txt`, `model_runs.json`

## Failure visibility

- [ ] Induce a NIM failure (bad key) — error visible in status, live log, and ModelRun viewer

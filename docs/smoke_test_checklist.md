# Message Evidence Workstation — Smoke Test Checklist

Use the sample dataset in `tests/fixtures/sample_dataset` unless you have a prepared normalized donor directory.

## Setup

- [ ] Create venv and `pip install -e ".[dev]"`
- [ ] `python -m pytest -q` passes (fast suite; scale tests excluded)
- [ ] `python -m pytest -m scale -q` passes for manual/nightly large-fixture validation
- [ ] `python -m message_evidence_workstation.app` launches

## Load Dataset tab

- [ ] On first launch, **Home** tab is visible; dataset-dependent tabs (Simple Search, Conversational, Output Formatting, Transcript Widget) are disabled
- [ ] **Setup / Settings** tab remains enabled before a dataset is loaded
- [ ] Browse to a normalized dataset directory (`dataset.json`, `source_threads.jsonl`, `messages.jsonl`)
- [ ] Import-only succeeds; narration shows thread/message counts and largest-thread warning when applicable
- [ ] Background embedding runs after import; status bar shows progress (message then chunk phases)
- [ ] Embedding search modes are greyed out until the active model's indexes are ready
- [ ] After successful load, **Home** tab stays visible and Load button is disabled for the session
- [ ] Reopening the app does not auto-activate a previously imported dataset (manual load from Home)
- [ ] Failed import leaves import validity **failed**, keeps Home tab, and does not enable dataset tabs

## Dataset

- [ ] Sidebar shows source threads and evidence block categories
- [ ] Selecting a source thread opens the Transcript Widget tab
- [ ] Large threads use virtualized scrolling (scroll deep without loading all rows into the widget)

## New Transcript Widget (document demonstrator)

- [ ] **New Transcript Widget** tab appears beside **Transcript Widget**
- [ ] Source thread combo loads a document-style read-only transcript
- [ ] **Jump 50** / **Jump 500** scroll directly to deep messages
- [ ] **New evidence block** and **Jump random + create block** create DB evidence blocks
- [ ] Active block shows context/relevant shading, hit marker, and highlight toggles in the margin
- [ ] Dragging context/relevant boundaries persists on release; **Persist / reload** round-trips state
- [ ] Simple Search and Conversational tabs still use the legacy transcript widget only

## Virtual Transcript Widget (Gen 3 demonstrator)

- [ ] **Virtual Transcript Widget** tab appears beside the other transcript tabs
- [ ] Opening the tab loads thread metadata only (status shows message count; cache stays small)
- [ ] **Jump 50**, **Jump 500**, and **Jump 14,000** on a large thread respond without hanging
- [ ] **Create at viewport center** / **Create at random message** create evidence blocks near deep ordinals
- [ ] Active block shows context/relevant shading, labeled boundary handles, hit marker, and highlight toggles
- [ ] Dragging boundaries persists on release; **Reload thread** restores DB state
- [ ] Simple Search and Conversational tabs still use the legacy transcript widget only

## Evidence blocks

- [ ] Create a category from sidebar `+`
- [ ] Simple Search finds `allergy` hits
- [ ] Drag a grouped result into a category (creates an evidence block)

## Simple Search

- [ ] Select a search mode (FTS5, expanded keyword, message embedding, or chunk embedding)
- [ ] Typing in the query box does **not** run a search until **Search** or Enter
- [ ] **Cancel** stops an in-flight search and does not render stale results
- [ ] FTS5 / expanded keyword show total hit count and page controls
- [ ] Embedding modes label results as top-K by similarity (no FTS-style pagination)
- [ ] Next/previous page fetches additional hits without silent caps
- [ ] Page size and result list update correctly when query changes

## Context window (required before conversational use)

- [ ] Settings → **Model context window (tokens)** starts unset (zero/blank)
- [ ] Conversational Interface shows a blocking message until context window is configured
- [ ] After setting context window and saving, budget preview and conversational modes become available
- [ ] Whole-transcript mode is only offered when SQL budget stats fit the configured window

## NIM (requires API key + model in Setup / Settings)

- [ ] Keyword expansion returns yellow chips / expanded hits
- [ ] Conversational whole-transcript answer completes (small dataset only)
- [ ] Conversational exhaustive window scan completes
- [ ] Conversational session-coverage answer completes (legacy path; lower recall than exhaustive)

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

## Output formatting and print preview

- [ ] Open Output Formatting tab; default printable artifact group is visible
- [ ] Drag an evidence block onto a group to create a printable artifact
- [ ] Drag another evidence block onto the artifact to append it
- [ ] Edit title, exhibit number, and case number; Save metadata
- [ ] Move blocks up/down and remove an included block
- [ ] Preview shows paged content with footer and end-of-artifact provenance ledger
- [ ] Print preview widget supports print and PDF export from the real layout engine

## Removed legacy surfaces

- [ ] No **Workstation Conversation** tab or HTML conversation export in the app

## Audit

- [ ] Settings → export process log JSON/text
- [ ] Settings → ModelRun list shows routed runs after model use (check `provider` + `task_role` in raw JSON)
- [ ] Export audit bundle writes `process_log.json`, `process_log.txt`, `model_runs.json`

## Failure visibility

- [ ] Induce a NIM failure (bad key) — error visible in status, live log, and ModelRun viewer

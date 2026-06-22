# Message Evidence Workstation — Build Plan

## 1. Build Goal

Build a Python desktop MVP that lets a user load normalized message data, browse source threads, search messages using FTS5/keyword expansion/embeddings, drag results into categories as workstation conversations, use a NIM-backed conversational interface to search the dataset, and prepare selected conversations for court-oriented output.

The MVP is a proof workstation, not a final legal filing product.

## 2. Core Architectural Shape

Use a layered but concrete Python application:

```text
message_evidence_workstation/
  app.py
  config/
  db/
    connection.py
    schema.py
    migrations.py
    repositories.py
  domain/
    models.py
    constants.py
  logging_ui/
    process_log.py
    log_bus.py
  importers/
    normalized_loader.py
  search/
    fts.py
    grouping.py
    result_models.py
    fusion.py
  nim/
    client.py
    prompts.py
    model_runs.py
  embeddings/
    model_registry.py
    adapters.py
    sqlite_vec_backend.py
    index_jobs.py
    chunking.py
  ui/
    main_window.py
    sidebar.py
    settings_tab.py
    source_thread_view.py
    simple_search_tab.py
    conversational_tab.py
    output_formatting_tab.py
  export/
    html_preview.py
  tests/
```

This structure is intentionally simple. Do not build a plugin framework. A small NIM wrapper and small embedding adapter layer are acceptable because they isolate real behavior, not because the app is pretending providers are interchangeable.

## 3. Provisional Test Data Contract

The final import pipeline is out of scope. For MVP testing, implement one normalized fixture loader that can ingest a directory shaped like this:

```text
sample_dataset/
  dataset.json
  source_threads.jsonl
  messages.jsonl
```

`dataset.json`:

```json
{
  "name": "Donor Dataset 001",
  "notes": "normalized test dataset"
}
```

`source_threads.jsonl`, one object per line:

```json
{"source_thread_id":"thread_001","source_platform":"facebook","platform_thread_id":"abc","display_title":"Jane Doe","participant_summary":"Art, Jane","start_ts":"2024-01-01T10:00:00","end_ts":"2024-01-03T11:00:00","metadata_json":{}}
```

`messages.jsonl`, one object per line:

```json
{"message_id":"msg_001","source_thread_id":"thread_001","source_platform":"facebook","source_message_id":"abc-1","timestamp":"2024-01-01T10:00:00","sender_id":"art","sender_display":"Art","body":"Did you ask the school about the allergy form?","has_attachment":false,"attachment_summary":"","sort_index":1,"source_metadata_json":{}}
```

This is test plumbing only. It does not decide the final raw importer shape.

## 4. Database Strategy

Use a single SQLite database per workspace/project. Initialize schema on startup and run simple ordered migrations.

Required first-wave tables:

- `dataset`
- `source_thread`
- `message`
- `category`
- `workstation_conversation`
- `conversation_hit`
- `conversation_range`
- `message_highlight_override`
- `prompt_template`
- `model_run`
- `embedding_index_metadata`
- `process_log`
- `message_fts` virtual table
- sqlite-vec virtual tables for message and chunk vectors once that phase is reached

The `message` table is immutable after load. User decisions live in separate tables.

## 5. UI Build Strategy

Build the PySide6 UI in vertical slices:

1. Main shell and persistent left sidebar.
2. Settings/log tab first enough to make failures visible.
3. Source-thread/message viewer.
4. Categories and workstation conversations.
5. Simple Search.
6. NIM keyword expansion.
7. Embedding indexes and vector results.
8. Conversational Interface.
9. Output Formatting.
10. Export preview.

During MVP, favor visible debug panels over polish.

## 6. Logging Strategy

Every service gets a shared `ProcessLogger` that writes to both:

1. a Qt signal/log bus for live UI display,
2. the persisted `process_log` table.

Log entries should include severity, component, operation, short message, optional structured details, exception type, and stack trace.

No silent failures. A failed NIM call, sqlite-vec load, embedding model load, schema migration, vector dimension mismatch, or dataset parse error must be visible.

## 7. Search Strategy

### FTS5

Start with message-level FTS5.

- Exact matches: bright green.
- Partial matches: light green.
- Debounce typing.
- Log query text, normalized query, elapsed time, result count, and row IDs.

### Keyword Expansion

Use NIM to produce search-term chips. Chips feed back into FTS5. Yellow results are shown below direct FTS results.

### Embeddings

Use local embedding models, selected in Settings. Store vectors using sqlite-vec.

- Message vectors produce purple results.
- Chunk vectors produce pink results.
- Show distance/rank/debug details.
- No silent fallback if sqlite-vec fails.

### Fusion and Grouping

Visible result rows should avoid duplicate spam.

Initial grouping rule:

- same `source_thread_id`, and
- hit messages within 5 messages or 30 minutes.

Log every grouping decision during MVP.

## 8. NIM Strategy

All MVP LLM-style calls use NVIDIA NIM.

Required prompt types:

1. Keyword Expansion
2. Conversational Search Planner
3. Conversational Search Result Synthesis
4. Evidence/Conversation Range Suggestion

Use a concrete `NimClient` with OpenAI-compatible chat-completions style methods. Store every call in `model_run`, including model, prompt version, input summary, raw request/response JSON, latency, and errors.

The LLM may propose actions. It must not directly mutate the database.

## 9. Embedding Strategy

Initial selectable models:

- `Qwen/Qwen3-Embedding-0.6B`
- `google/embeddinggemma-300m`
- `sentence-transformers/all-MiniLM-L6-v2`
- `nomic-ai/nomic-embed-text-v1` or local equivalent

Implement adapters incrementally. The UI should show model load status, dimensions, revision if known, and index status.

Do not let dimension mismatches produce confusing empty results. Fail loudly and log the expected/actual dimensions.

## 10. sqlite-vec Strategy

Treat sqlite-vec as an experiment that needs instrumentation.

Required validation action:

- extension path exists,
- extension loads,
- version detected if possible,
- test vector table can be created,
- known vectors can be inserted,
- known nearest-neighbor query returns expected row,
- dimension mismatch error is captured and shown.

Do not switch to FAISS/LanceDB/brute force automatically.

## 11. Output Formatting Strategy

The output tab opens a workstation conversation but displays the full source thread. The user adjusts four boundaries:

1. context lead-in start,
2. relevant start,
3. relevant end,
4. context lead-out end.

Initial boundaries come from the NIM range suggestion prompt unless the user has locked/modified the range.

Display states:

- hit: bold green,
- relevant: green,
- context: yellow,
- other: normal.

User overrides always win.

## 12. Testing Strategy

Use pytest for service/database/search tests. Use manual acceptance checks for UI tickets until automated Qt testing is worth it.

Minimum test areas:

- schema creation,
- fixture load,
- process logging,
- FTS exact/partial behavior,
- grouping/fusion,
- category/workstation conversation creation,
- NIM client mocked success/failure,
- prompt version selection,
- embedding adapter interface with a tiny fake model,
- sqlite-vec validation path, with skipped tests when extension is unavailable,
- HTML export generation.

## 13. Ticket Stack Overview

- T00 Repo Bootstrap
- T01 SQLite Schema and Process Log
- T02 Normalized Dataset Loader
- T03 PySide6 Shell, Sidebar, and Settings Log
- T04 Source Thread and Message Viewer
- T05 Categories and Workstation Conversations
- T06 FTS5 Indexing
- T07 Simple Search UI and Result Grouping
- T08 Drag Search Results to Categories
- T09 NIM Settings and Client
- T10 Prompt Templates and ModelRun Audit
- T11 Keyword Expansion Search
- T12 Embedding Model Registry and Adapters
- T13 sqlite-vec Validation and Diagnostics
- T14 Message Embedding Index
- T15 Chunk Embedding Index
- T16 Embedding Search UI Integration
- T17 Conversational Search Planner and Tools
- T18 Conversational Result Synthesis
- T19 Output Formatting View
- T20 Range Suggestion and Highlight Overrides
- T21 HTML Export Preview
- T22 Audit and Log Export
- T23 Packaging and Final Smoke Tests

## 14. Clean-Agent Guardrails

Do not add:

- generic multi-provider LLM system,
- local LLM MVP support,
- account/login system,
- cloud sync,
- automatic legal conclusions,
- final court templates,
- generic JSON workflow executor,
- silent vector fallback,
- hidden debug logging.

When a decision is unclear, choose the smallest visible/testable behavior that preserves the spec and logs what happened.

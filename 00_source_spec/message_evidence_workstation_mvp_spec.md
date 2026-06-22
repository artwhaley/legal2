# Message Evidence Workstation — MVP Build Spec

Updated: 2026-06-21

## 1. Purpose

Build a Python desktop workstation for analyzing real donor message datasets, finding topic-specific message passages, categorizing them, and preparing those passages for court-oriented exhibit output.

The MVP deliberately skips raw import plumbing. Test data is provided in an already-normalized local format. Import from phone exports, Facebook, WhatsApp, Google Voice, etc. is outside this spec.

This is not a final legal filing product. It is a tool for proving the search, review, categorization, and output-preparation workflow.

## 2. Major Product Decisions

These are intentional decisions for this version. Do not replace them with generic app assumptions.

1. **Python throughout the MVP.**
   - UI, search, database, embeddings, NIM calls, and instrumentation should all be Python unless a concrete blocker appears.

2. **NVIDIA NIM is the required LLM provider for MVP.**
   - All LLM-style calls use NVIDIA NIM during this phase.
   - Local LLMs are a later experiment, not part of the MVP target.
   - Do not implement vague provider abstraction that hides the actual behavior.
   - A small provider wrapper is acceptable only to keep NIM call code isolated and testable.

3. **Local embedding models are part of MVP.**
   - Embedding model selection and embedding recomputation are first-class setup tasks.

4. **sqlite-vec is the first vector-store target.**
   - We are intentionally testing sqlite-vec because a SQLite-native vector path may simplify the app.
   - Instrument it heavily.
   - Do not silently fall back to another vector engine.
   - If sqlite-vec fails, the app should fail loudly, explain where it failed, and write detailed diagnostics to the log.

5. **No silent failures.**
   - Errors should be visible.
   - Background jobs should report progress, failures, timing, and counts.
   - During MVP, noisy logs are a feature, not a bug.

6. **The user’s domain term “conversation” means a topic/exhibit-sized passage.**
   - It does not mean the entire app-defined thread between two people.
   - It may be one message, a handful of messages, or a multi-day passage.
   - In court-output terms, a conversation is the user-curated unit that may become an exhibit.

## 3. Terminology

Terminology matters because messaging apps use “conversation” differently from this project.

### Source Thread

A source thread is the raw app-level communication stream: for example, a Facebook Messenger thread, WhatsApp chat, Google Voice contact thread, or SMS thread.

A source thread may span years and thousands of messages.

Source threads are not the unit of categorization or export.

### Message

A single normalized message from the dataset.

Messages are immutable source records. User annotations, AI output, highlights, and export decisions live separately.

### Workstation Conversation

A workstation conversation is a topic-specific passage selected with help from search and AI tools.

This is the user’s intended meaning of “conversation” in this project.

Examples:

- one message about a missed pickup,
- a short exchange about school,
- a two-day string of messages about allergies,
- a selected passage from a much longer source thread.

A workstation conversation is the thing that gets added to a category and later prepared as an exhibit.

Implementation note: code may call this object `EvidenceConversation`, `ConversationItem`, or another explicit name to avoid confusing it with `SourceThread`.

### Category

A user-created bucket such as `school`, `work`, `allergies`, or `trip to orlando`.

Categories contain workstation conversations.

### Hit / Epicenter

A hit is an individual message that caused search or AI retrieval to identify a passage.

The hit message is the epicenter of the candidate conversation. A conversation can have more than one hit.

### Relevant Range

The user-selected passage that directly matters for the category/output.

### Context Range

Messages before and after the relevant range that should be included to show the passage fairly and avoid cherry-picking.

## 4. Core UI Shape

The application has two primary divisions:

1. a persistent left sidebar,
2. a right-side workflow area that changes by tab.

## 5. Persistent Left Sidebar

The left sidebar contains tools used across workflows.

### 5.1 Source Thread Selector

At the top is a scrollable source-thread selector for the current dataset.

This lets the user inspect raw source threads, but source threads are not the main category payload.

### 5.2 Category Area

Below the source-thread selector is a large collapsible category area.

The user can:

- create categories with a `+` button,
- rename categories,
- collapse/expand categories,
- drag search results into categories,
- view workstation conversations already assigned to a category.

Dragging a search result onto a category creates a new workstation conversation or adds another hit to an existing nearby workstation conversation, depending on merge rules.

## 6. Right-Side Workflow Tabs

Initial right-side tabs:

1. Simple Search
2. Conversational Interface
3. Output Formatting
4. Setup / Settings

## 7. Recommended MVP Stack

Use Python throughout.

Recommended stack:

- UI: PySide6 / Qt
- Database: SQLite
- Text search: SQLite FTS5
- Vector search: sqlite-vec
- Local embedding models: model-specific Python adapters around sentence-transformers / transformers / llama.cpp-style local runtimes where needed
- LLM provider: NVIDIA NIM
- Background jobs: Qt worker threads or Python process workers
- Logs: in-app log sink plus persistent process log table
- Export preview: HTML first
- Court-ready PDF export: later hardening step

## 8. Data Model

This schema is conceptual. Actual DDL can evolve during implementation, but these object boundaries should stay stable.

### 8.1 Dataset

Represents one loaded donor/test dataset.

Fields:

- `dataset_id`
- `name`
- `created_at`
- `schema_version`
- `notes`

### 8.2 SourceThread

Represents the app-level message thread.

Fields:

- `source_thread_id`
- `dataset_id`
- `source_platform`
- `platform_thread_id`
- `display_title`
- `participant_summary`
- `start_ts`
- `end_ts`
- `message_count`
- `metadata_json`

### 8.3 Message

Represents a normalized immutable source message.

Fields:

- `message_id`
- `dataset_id`
- `source_thread_id`
- `source_platform`
- `source_message_id`
- `timestamp`
- `sender_id`
- `sender_display`
- `body`
- `body_normalized`
- `has_attachment`
- `attachment_summary`
- `sort_index`
- `source_metadata_json`

Messages are immutable after load.

### 8.4 Category

A user-created bucket.

Fields:

- `category_id`
- `dataset_id`
- `name`
- `description`
- `color`
- `is_collapsed`
- `created_at`
- `updated_at`

### 8.5 WorkstationConversation

The topic/exhibit-sized unit the user is building.

Fields:

- `workstation_conversation_id`
- `dataset_id`
- `category_id`
- `source_thread_id`
- `primary_hit_message_id`
- `title`
- `user_notes`
- `status` — `candidate`, `accepted`, `rejected`, `export_ready`
- `created_by` — `simple_search`, `conversational_search`, `manual`
- `created_at`
- `updated_at`

### 8.6 ConversationHit

A message that contributed to finding or justifying a workstation conversation.

Fields:

- `conversation_hit_id`
- `workstation_conversation_id`
- `message_id`
- `retrieval_method` — `fts_exact`, `fts_partial`, `keyword_expansion`, `message_embedding`, `chunk_embedding`, `llm_planner`, `manual`
- `query_text`
- `matched_term`
- `score`
- `rank`
- `distance`
- `explanation`
- `metadata_json`

### 8.7 ConversationRange

The user-adjustable output boundaries.

Fields:

- `conversation_range_id`
- `workstation_conversation_id`
- `lead_in_start_message_id`
- `relevant_start_message_id`
- `relevant_end_message_id`
- `lead_out_end_message_id`
- `llm_suggested_json`
- `user_modified`
- `locked`

### 8.8 MessageHighlightOverride

Per-message user highlight override.

Fields:

- `override_id`
- `workstation_conversation_id`
- `message_id`
- `highlight_state` — `none`, `hit`, `relevant`, `context`
- `user_modified`

User overrides always beat AI suggestions.

### 8.9 PromptTemplate

Editable system/user prompts used by NIM calls.

Fields:

- `prompt_template_id`
- `name`
- `run_type`
- `body`
- `version`
- `is_active`
- `created_at`
- `updated_at`

### 8.10 ModelRun

Audit record for every NIM call.

Fields:

- `model_run_id`
- `dataset_id`
- `run_type`
- `provider` — `nvidia_nim`
- `model`
- `prompt_template_id`
- `input_summary`
- `raw_request_json`
- `raw_response_json`
- `created_at`
- `latency_ms`
- `error_type`
- `error_message`
- `stack_trace`

### 8.11 EmbeddingIndexMetadata

Tracks embedding index state.

Fields:

- `embedding_index_id`
- `dataset_id`
- `granularity` — `message`, `chunk`
- `backend` — initially `sqlite_vec`
- `model_name`
- `model_revision`
- `dimensions`
- `distance_metric`
- `normalization_mode`
- `chunking_config_json`
- `sqlite_vec_version`
- `extension_path`
- `created_at`
- `status` — `missing`, `building`, `ready`, `failed`, `stale`
- `message_count`
- `chunk_count`
- `last_error`

### 8.12 ProcessLog

Persistent noisy instrumentation log.

Fields:

- `process_log_id`
- `dataset_id`
- `timestamp`
- `severity` — `debug`, `info`, `warning`, `error`
- `component`
- `operation`
- `message`
- `details_json`
- `exception_type`
- `stack_trace`

## 9. Setup / Settings Tab

The Setup / Settings tab is not an afterthought. It is where we configure models, recompute indexes, edit prompts, and inspect what the app is doing.

### 9.1 NIM Settings

Fields:

- API base URL
- API key
- model dropdown
- refresh model list button
- temperature
- max output tokens
- timeout
- streaming on/off

Requirements:

- All LLM calls use NIM for MVP.
- The model dropdown should be populated from the NIM-compatible model list when available.
- If model-list retrieval fails, show the failure loudly in the settings log and allow manual model-name entry only as an explicit fallback.
- Do not hardcode the list of NIM models.

### 9.2 Prompt Editors

The settings screen includes editable prompts for each LLM call type.

Initial prompt types:

1. Keyword Expansion
2. Conversational Search Planner
3. Conversational Search Result Synthesis
4. Evidence/Conversation Range Suggestion

The user originally identified three prompt types. The fourth is required because output formatting needs its own range-selection behavior.

Every prompt edit creates or updates a versioned prompt template record.

### 9.3 Embedding Model Selector

Initial embedding model options:

- `Qwen/Qwen3-Embedding-0.6B`
- `google/embeddinggemma-300m`
- `sentence-transformers/all-MiniLM-L6-v2`
- `nomic-ai/nomic-embed-text-v1` or the local runtime equivalent for Nomic Embed Text

Requirements:

- The selected embedding model determines which indexes are valid.
- Changing model invalidates or marks stale the existing message/chunk indexes for that dataset.
- The app must show which embedding indexes exist, which are stale, and which failed.

### 9.4 Embedding Jobs

Actions:

- compute/recompute message embeddings,
- compute/recompute conversation-chunk embeddings,
- clear embeddings for selected model,
- validate sqlite-vec backend,
- run vector-search smoke test.

Each job reports:

- start time,
- model name,
- model revision if available,
- dimensions,
- number of messages/chunks to process,
- number completed,
- failures,
- elapsed time,
- inserts per second,
- query smoke-test results.

### 9.5 Verbose Log Window

The settings page includes a log window for MVP.

Requirements:

- live tail of process logs,
- severity filter,
- component filter,
- copy selected log entry,
- clear visible log view without deleting persisted logs,
- export log to text/JSON,
- show stack traces for exceptions,
- show raw operation IDs for debugging.

This log window is intentionally noisy. It can be hidden or redesigned later.

## 10. sqlite-vec Integration and Instrumentation

sqlite-vec is the primary vector backend for MVP testing.

### 10.1 Goals

Use sqlite-vec to keep vector search close to the SQLite/FTS5 data store.

We are testing:

- install/package reliability,
- extension loading on Windows,
- vector insert reliability,
- query correctness,
- speed on realistic donor datasets,
- result stability,
- whether distances look sane,
- how well message vectors and chunk vectors complement FTS5.

### 10.2 No Silent Fallback

If sqlite-vec cannot load, initialize, insert, or query, the app should:

1. mark the vector backend as failed,
2. show the user a visible error,
3. write full diagnostics to `ProcessLog`,
4. disable embedding search buttons that depend on the failed index,
5. avoid pretending vector search succeeded.

Do not automatically switch to FAISS, LanceDB, brute-force Python cosine search, or any other fallback unless the user explicitly enables a debug fallback later.

### 10.3 Startup Validation

The app should include a `Validate sqlite-vec` action.

It should check:

- extension file exists,
- extension loads,
- sqlite-vec version if exposed,
- expected vector table can be created,
- a known vector can be inserted,
- a known nearest-neighbor query returns the expected row,
- dimension mismatch errors are visible and understandable,
- database path and extension path are logged.

### 10.4 Index Build Instrumentation

During embedding index build, log:

- model selected,
- embedding dimension detected,
- normalization mode,
- vector serialization format,
- number of source records,
- records skipped and why,
- insert batch sizes,
- timing per stage,
- sqlite errors,
- first few vector lengths/checksums for sanity,
- count of rows after insert,
- index metadata status.

### 10.5 Query Instrumentation

For each vector query, log:

- query text,
- embedding model,
- embedding dimension,
- query vector norm,
- top K requested,
- top K returned,
- raw distances,
- message IDs/chunk IDs returned,
- source thread IDs returned,
- short text snippets for debug display,
- elapsed query time,
- any filtering or fusion step applied after vector retrieval.

### 10.6 Debug Result Display

In Simple Search, vector result rows should be able to expose debug details during MVP:

- retrieval method,
- model,
- distance,
- rank,
- source thread,
- hit message ID,
- chunk ID if applicable,
- chunk message range,
- matched snippet.

This can later become a collapsible developer/debug panel.

## 11. Simple Search Workflow

The Simple Search tab gives direct access to the search harness that the conversational system will use.

### 11.1 Layout

Top to bottom:

1. Search box
2. Yellow Keyword Expansion toggle
3. Keyword chip box
4. Purple Message Embedding Search toggle
5. Pink Chunk Embedding Search toggle
6. Results list

### 11.2 Plain FTS5 Search

Typing into the search box immediately populates results using FTS5.

Use a debounce so the app feels live without launching wasteful queries on every keystroke.

Result colors:

- exact match: bright green,
- partial match: light green.

### 11.3 Keyword Expansion

The yellow toggle enables keyword expansion.

Flow:

1. User enters a query.
2. App sends the query to the NIM Keyword Expansion prompt.
3. NIM returns suggested terms.
4. Terms appear as chips.
5. Each chip has an `x` to remove it.
6. A `+` button lets the user add custom chips.
7. FTS5 runs using all active chips.
8. Expanded-keyword hits appear as yellow results below direct green results.

### 11.4 Message Embedding Search

The purple toggle enables message-level embedding search.

Flow:

1. Embed the search query using the selected local embedding model.
2. Search the sqlite-vec message index.
3. Add semantically similar individual message hits as purple results.
4. Display rank/distance in debug mode.

If no valid message embedding index exists, the button should explain that embeddings must be computed first.

### 11.5 Chunk Embedding Search

The pink toggle enables precomputed chunk embedding search.

Flow:

1. Embed the search query using the selected local embedding model.
2. Search the sqlite-vec chunk index.
3. Convert matched chunks back to source message ranges.
4. Choose a representative hit message inside the chunk.
5. Add pink results.
6. Display chunk boundaries and distance in debug mode.

### 11.6 Result Fusion and De-Duplication

Avoid duplicate spam.

Rules:

1. One hit message appears once in the visible result list.
2. A result row can have multiple retrieval-method badges.
3. Nearby hits in the same source thread should be grouped into a candidate workstation conversation.
4. Grouping should preserve all hit messages internally.
5. Exact FTS results sort before partial, keyword, message embedding, and chunk embedding results by default.

Initial grouping rule:

- same source thread,
- within 5 messages or 30 minutes of each other.

This rule is deliberately simple and should be made visible in logs/debug output.

### 11.7 Dragging Results to Categories

Dragging a result to a category creates a workstation conversation in that category.

The created workstation conversation stores:

- source thread,
- primary hit message,
- all grouped hits,
- retrieval methods,
- query text,
- preliminary title,
- status `candidate`.

## 12. Conversational Interface Workflow

This is the “talk with your document” workflow.

The conversational system has access to the dataset through real tools. It should not hallucinate access to the entire corpus in prompt context.

### 12.1 Required Behavior

For a user query, return:

1. a plain-language answer,
2. a summary of the search strategy,
3. a result window containing candidate workstation conversations that could be added to categories.

### 12.2 Tooling

The conversational planner may use tools such as:

- FTS5 search,
- keyword expansion,
- message embedding search,
- chunk embedding search,
- source thread reading,
- message range reading,
- hit grouping,
- candidate conversation creation proposal.

The LLM proposes search plans and explanations. The Python app executes the actual retrieval.

### 12.3 NIM Prompt Types

The conversational workflow uses at least two NIM prompt templates:

1. Conversational Search Planner
2. Conversational Search Result Synthesis

Planner output should be structured enough for Python to execute, but do not build a generic JSON behavior executor. This planner is specific to this workflow.

### 12.4 Mutation Rule

The LLM may propose candidate workstation conversations, but it does not directly mutate the database.

The app creates/updates records only through explicit Python code paths.

## 13. Output Formatting Workflow

The Output Formatting tab is where categorized workstation conversations are prepared for export.

### 13.1 Layout

The view includes:

- category/conversation selector,
- full source-thread scroll view,
- hit/relevance/context legend,
- draggable range handles,
- per-message highlight controls,
- export preview,
- notes/debug/audit panel.

### 13.2 Full Source Thread View

Even though the workstation conversation is only a selected passage, the output workflow displays the full source thread in a scroll view.

This allows the user to verify context and adjust boundaries.

### 13.3 Initial AI Range Guess

When a workstation conversation opens without locked user boundaries, the app calls the NIM Evidence/Conversation Range Suggestion prompt.

The prompt should propose:

1. relevant passage start,
2. relevant passage end,
3. lead-in/context start,
4. lead-out/context end.

The range suggestion may use the hit message, nearby messages, and optionally embeddings/concept analysis.

### 13.4 Highlighting Rules

Display states:

- primary hit message: bold + green,
- relevant passage: green,
- context lead-in/lead-out: yellow,
- all other text: normal black/white.

The user can:

- drag handles to set lead-in start,
- drag handles to set relevant start,
- drag handles to set relevant end,
- drag handles to set lead-out end,
- toggle individual message highlights on/off,
- override individual message states.

User edits always override AI suggestions.

### 13.5 Export Preparation

The MVP should produce an HTML preview first.

The export should include:

- category name,
- workstation conversation title,
- source platform,
- source thread title/participants,
- selected message passage,
- context messages,
- clear visual distinction between hit/relevant/context messages,
- optional notes,
- audit appendix if enabled.

PDF export can come after the HTML output is stable.

## 14. Logging and Instrumentation Principles

The app should be loud during MVP.

### 14.1 Log Everything Important

Log:

- dataset load,
- schema migration,
- FTS5 index creation,
- FTS5 query text and result counts,
- NIM request start/end/error,
- prompt template version,
- embedding model load,
- embedding dimensions,
- embedding job progress,
- sqlite-vec extension load,
- sqlite-vec insert/query results,
- result fusion/grouping decisions,
- drag-to-category actions,
- AI range suggestions,
- user range modifications,
- export generation.

### 14.2 Fail Loudly

Failures should be visible in three places:

1. immediate UI error or status area,
2. settings log window,
3. persisted `ProcessLog` table.

### 14.3 Avoid App-Shaped Magic

Do not hide uncertain behavior behind “smart” generic abstractions.

If the app does something heuristic, log the heuristic.

Examples:

- why two hits were grouped,
- why a chunk hit chose a particular representative message,
- why an index was marked stale,
- why a NIM model list could not be loaded,
- why a vector search returned no results.

## 15. Build Phases

### Phase 1 — Shell, Dataset, Source Threads, Messages

Build:

- PySide6 shell,
- SQLite schema,
- normalized dataset loader,
- source-thread selector,
- message viewer,
- settings log window,
- process log table.

Acceptance criteria:

- dataset loads,
- source threads appear in sidebar,
- selecting a source thread shows messages,
- logs visibly report load/index steps,
- failures show in UI and log.

### Phase 2 — Categories and Workstation Conversations

Build:

- category CRUD,
- category collapse/expand,
- workstation conversation records,
- manual creation from selected messages,
- display of conversations inside categories.

Acceptance criteria:

- user can create `school`, `work`, etc.,
- user can create a workstation conversation from a message/range,
- source thread and selected messages remain linked.

### Phase 3 — Plain FTS5 Simple Search

Build:

- FTS5 message index,
- debounced search box,
- exact/partial match distinction,
- green result display,
- result grouping,
- drag result to category.

Acceptance criteria:

- typing search text populates results,
- exact and partial matches are visually distinct,
- dragging a result creates a workstation conversation,
- logs show query text, timing, result count, and grouping decisions.

### Phase 4 — NIM Keyword Expansion

Build:

- NIM settings,
- model dropdown/model refresh,
- keyword expansion prompt editor,
- keyword chips,
- yellow expanded search results,
- ModelRun audit records.

Acceptance criteria:

- keyword expansion calls NIM,
- chips can be removed/added,
- expanded hits appear separately,
- NIM failures are visible and logged.

### Phase 5 — sqlite-vec and Embeddings

Build:

- embedding model selector,
- sqlite-vec validation action,
- message embedding index,
- chunk embedding index,
- vector search smoke test,
- purple/pink result integration.

Acceptance criteria:

- selected embedding model computes vectors,
- sqlite-vec stores and queries vectors,
- message embedding search returns purple results,
- chunk embedding search returns pink results,
- raw distances and debug details are visible/logged,
- sqlite-vec failure never silently falls back.

### Phase 6 — Conversational Interface

Build:

- chat-style interface,
- NIM planner prompt,
- deterministic Python tool execution,
- NIM result synthesis prompt,
- candidate conversation result panel.

Acceptance criteria:

- natural-language query returns answer + strategy summary + candidate conversations,
- tool calls are logged,
- LLM does not directly mutate category/conversation records.

### Phase 7 — Output Formatting

Build:

- category/conversation selector,
- full source-thread scroll view,
- initial NIM range suggestion,
- draggable range handles,
- per-message highlight override,
- HTML export preview.

Acceptance criteria:

- opening a candidate shows the whole source thread,
- hit/relevant/context highlighting works,
- user can adjust all boundaries,
- user overrides persist,
- HTML preview reflects current selections.

### Phase 8 — Audit and Export Hardening

Build:

- richer model run viewer,
- prompt version viewer,
- export audit appendix,
- log export,
- packaging cleanup.

Acceptance criteria:

- user can inspect why an item exists,
- app can export logs/audit data,
- generated output is reproducible from stored records.

## 16. Open Decisions

Do not invent answers to these without asking.

1. What exact normalized donor-data format will the MVP loader accept?
2. Should workstation conversations be allowed to span multiple source threads/platforms, or only one source thread at a time?
3. When two search hits are close together, when should they merge into one workstation conversation versus remain separate candidates?
4. How much raw donor text should be stored in NIM ModelRun logs?
5. Should export output include AI explanations, or should AI only help with internal preparation?
6. What is the first target export format after HTML preview: PDF, DOCX, or printable HTML?
7. Should categories have colors chosen by the user, or fixed app-generated colors?
8. Should every NIM prompt be editable immediately, or should prompt editing start as a developer-only settings panel?

## 17. Anti-Requirements

Do not add these unless explicitly requested:

- generic multi-provider LLM abstraction,
- local LLM execution for MVP,
- privacy-mode defaults not requested by the user,
- automatic legal conclusions,
- final court filing templates,
- generic JSON workflow executor,
- cloud sync,
- account system,
- polished hiding of debug logs,
- silent vector backend fallback,
- automatic mutation by LLM output.


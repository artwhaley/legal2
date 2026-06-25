# T56 - Virtualized Transcript

## Goal
Implement windowed transcript data + layout so large threads scroll smoothly without loading every message into memory.

## Background
`EvidenceTranscriptModel.load_messages` and full-thread reflow freeze the UI on large threads. Product UX: infinite scroll abstraction.

**Spec reference:** `04_pre_scale_hardening_spec.md` §4

## Depends On
- T52 (batched block highlights for thread load)
- T55 (watchdog warning at load — optional integration)

## Scope
- New `TranscriptDataSource` abstraction:
  - `message_count(thread_id)`
  - `fetch_messages(thread_id, start_index, count)` — SQL LIMIT/OFFSET or keyset on `(timestamp, sort_index, message_id)`
  - `fetch_evidence_blocks(thread_id)`
  - `fetch_block_highlights(block_ids)` — batched
- Refactor `EvidenceTranscriptModel` to hold visible window only (~viewport ± buffer rows)
- Refactor `Gen2TranscriptSurfaceWidget`:
  - Estimated/cached row heights
  - Total scroll extent from height sum
  - Fetch + layout on scroll with overscan
  - Recycle row widgets
- Evidence block editing by `message_id` + slot indices (not full-array row indices)
- Debounced overlay persistence unchanged in behavior
- Update `EvidenceBlockTranscriptWidget`, `TranscriptWidgetTab`, Simple Search transcript host

## Guardrails
- Printable/export paths unchanged (slot-bounded loads)
- Do not break evidence block create/edit/save flows
- Memory must not grow linearly with scroll depth beyond cache

## Non-Goals
- Web/client-server API
- Whole-dataset transcript for conversational answer (separate concern)

## Acceptance Criteria
- 10k+ message fixture: scroll and navigate to `message_id` within 500ms (perf test, `@pytest.mark.scale` OK)
- Memory stable when scrolling deep into large thread (instrumentation or scale test note)
- Existing evidence-block editing tests pass or are updated

## Tests
- Unit tests for `TranscriptDataSource` paging
- UI/perf smoke on generated large thread fixture
- Evidence block editing regression tests
- `python -m pytest -q`

# T12 — Embedding Model Registry and Adapters

## Goal

Create the local embedding model selection system and adapter interface without building the sqlite-vec index yet.

## Dependencies

T03, T01.

## Implementation Notes

Settings should list the initial embedding models from the spec. Implement an adapter interface with `load()`, `embed_texts()`, dimension detection, model name/revision, normalization mode, and failure reporting. Start with all-MiniLM-L6-v2 if that is fastest to run locally, but keep the listed models present as selectable entries with clear availability/load errors. Include a fake adapter for tests.

## Files / Areas Likely Touched

- message_evidence_workstation/embeddings/model_registry.py
- message_evidence_workstation/embeddings/adapters.py
- message_evidence_workstation/ui/settings_tab.py
- tests/test_embedding_adapters.py

## Acceptance Criteria

- Settings tab shows the four requested embedding options.
- Selecting a model records current embedding model setting.
- Adapter exposes dimension after load.
- Adapter load errors are visible/logged.
- Fake adapter supports deterministic test embeddings.
- Changing model marks existing indexes stale if metadata exists.

## Tests / Verification

- Unit test fake adapter.
- Unit test model registry entries.
- Manual test selecting unavailable model logs clear error.

## Non-Goals

- No vector storage yet.
- No automatic huge downloads without explicit user action.
- No local LLM support.

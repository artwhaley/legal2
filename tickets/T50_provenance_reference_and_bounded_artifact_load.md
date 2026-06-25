# T50 - Provenance Reference Model And Bounded Artifact Load

## Goal
Enforce the canonical reference model: analysis payloads stay light; provenance resolves from DB by message ID. Fix metadata loss and bounded printable-artifact message loading.

## Background
`load_dataset_messages` hardcodes `source_metadata_json={}`, breaking provenance if those rows are used. Printable artifact context may load full threads then slice in memory, which is unacceptable at scale.

**Spec reference:** `04_pre_scale_hardening_spec.md` Section 6, Section E

## Depends On
- T48 (touches `load_dataset_messages` consumers; coordinate)

## Scope
- Fix `load_dataset_messages` to preserve `source_metadata_json` from SQL (parse JSON like repositories do).
- Confirm analysis serializers (`serialize_messages`, window text builders) **omit** metadata from prompt text; this is intentional token savings.
- Audit `load_printable_artifact_context` / `_messages_for_evidence_block`:
  - Must **not** call `list_messages_for_thread` + in-memory slice.
  - Use bounded SQL range/keyset fetch for each evidence block's slot range only.
- Add/extend repository helper: `fetch_messages_for_slot_range(conn, dataset_id, thread_id, start_slot, end_slot)` or equivalent.
- Unit test: rich `source_metadata_json` in DB -> window text excludes hash/path -> provenance ledger includes them.

## Guardrails
- Do not add `message_analysis` materialized view.
- Do not change provenance ledger format beyond correctness.
- Do not load full thread bodies in printable context path.

## Non-Goals
- Print layout engine and preview (T57-T58).
- Conversational whole-transcript load optimization.

## Acceptance Criteria
- `load_dataset_messages` preserves metadata when bodies are loaded.
- Printable artifact context loads only slot-bounded messages per block (verified by test or query spy).
- Provenance test passes per spec Section 6 acceptance criteria.

## Tests
- Test metadata preserved in `load_dataset_messages`.
- Test printable context does not fetch full thread row count when block spans subset.
- Provenance enriched metadata test (existing or new).
- `python -m pytest -q`

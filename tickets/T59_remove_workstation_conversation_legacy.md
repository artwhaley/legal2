# T59 - Remove Workstation Conversation Legacy

## Goal
Delete the obsolete `workstation_conversation` domain, related tables, HTML export, and tests. Evidence blocks + printable artifacts are the sole review/export unit.

## Background
Legacy workstation conversation tables and HTML preview remain in schema/repos but production UI uses evidence blocks. Existing table data is disposable test data.

**Spec reference:** `04_pre_scale_hardening_spec.md` §11, §19

## Depends On
- T58 preferred first (HTML replacement exists) — or delete HTML in same ticket if T58 not done

## Scope
- Remove production code:
  - Models: `WorkstationConversation`, `OutputConversationContext`, related dataclasses if unused
  - Repository functions: `create_workstation_conversation_from_search`, `load_output_conversation_context`, range/highlight helpers used only by legacy path
  - `export/html_preview.py`
  - `normalized_loader` cleanup deletes for workstation tables
- Schema migration: `DROP TABLE IF EXISTS` for:
  - `workstation_conversation`, `conversation_hit`, `conversation_range`, `message_highlight_override`
  - Bump `SCHEMA_VERSION`; idempotent migration
- Update `export/audit_export.py` — remove HTML conversation export; keep JSON/text process logs
- Remove/update tests: `test_html_export.py`, `test_ranges_highlights.py` workstation-specific tests, `test_output_context.py` if legacy-only
- Update smoke checklist / docs

## Guardrails
- **Do not** drop `evidence_block`, printable artifact, or category tables
- No backup/export precheck required (authoritative disposable data decision)
- Keep `display_states.py` if still used by evidence/transcript paths — audit before delete

## Non-Goals
- Session-coverage conversational path removal
- Obsolete prompt cleanup (T60)

## Acceptance Criteria
- No production imports of workstation conversation symbols or `html_preview`
- Migration drops legacy tables cleanly on fresh and existing workspaces
- Full `python -m pytest -q` passes
- Smoke checklist has no workstation conversation steps

## Tests
- Schema migration test: tables absent after migrate
- Grep CI check in review: no `workstation_conversation` in `message_evidence_workstation/` except migration changelog comment if any
- `python -m pytest -q`

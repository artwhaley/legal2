# T47 - Remove Archaic Answer Settings

## Goal
Remove four dead `AnswerSettings` fields and ensure `window_overlap_messages` is the one wired scan-tuning knob.

## Background
`whole_transcript_max_chars`, `max_inspected_sessions`, `window_target_tokens`, and `transcript_window_padding` appear in settings but do not drive behavior. Operators tuning them get false confidence. Overlap must remain for exhaustive scan.

**Spec reference:** `04_pre_scale_hardening_spec.md` §7

## Depends On
- T46 (context window wiring should be stable before overlap moves)

## Scope
- Remove from `AnswerSettings` dataclass and `settings.json` migration on load (silent strip of legacy keys)
- Remove from Settings tab answer form and any readout references
- Keep `window_overlap_messages`:
  - Move to `NimSettings` **or** keep as sole `AnswerSettings` scan field with label "Window overlap (messages)"
  - Default: `2`
  - Wire to `build_token_bounded_windows_for_dataset` / exhaustive scan (verify end-to-end)
- Remove `del max_chars` compatibility shim in `resolve_answer_mode` if field is gone
- Update tests and docs referencing removed fields

## Guardrails
- Do not remove `answer_strategy` or active conversational modes
- Do not touch session-coverage path beyond overlap wiring shared with scan

## Non-Goals
- Window packing formula changes (T49)
- SQL budget stats (T48)

## Acceptance Criteria
- `grep` finds zero production references to removed field names
- Settings file round-trips without removed keys
- Overlap value persists and affects window planner in tests

## Tests
- Settings load/save migration test strips legacy keys
- Window planner test with overlap=2 vs overlap=0 shows different window boundaries
- `python -m pytest -q`

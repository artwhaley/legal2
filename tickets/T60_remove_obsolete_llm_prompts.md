# T60 - Remove Obsolete LLM Prompts

## Goal
Remove obsolete prompt templates, settings UI entries, and task-role inventory for deleted features.

## Background
`evidence_range_suggestion`, planner/synthesis prompts, and related paths are obsolete. Seeds and UI still expose them.

**Spec reference:** `04_pre_scale_hardening_spec.md` §16

## Depends On
- T59 (range/HTML already gone — coordinate prompt list)

## Scope
- Remove prompt seeds / DB entries for:
  - `evidence_range_suggestion`
  - `conversational_search_planner`
  - `conversational_search_synthesis` (if unused)
- Remove from Settings prompt combo
- Remove `RANGE_SUGGESTION` from `llm/types.py` if unreferenced
- Clean `task_roles.py` obsolete inventory entries (or move to docs only)
- Migration or seed update: deactivate/delete obsolete prompt rows in existing workspaces

## Guardrails
- Keep active run types: expansion, research, writing, conversational answer modes, session summary, coverage audit
- Do not remove conversational answer prompts

## Non-Goals
- Session-coverage path deletion
- Model router changes

## Acceptance Criteria
- `grep range_suggestion` / `RUN_TYPE_RANGE_SUGGESTION` — no production matches
- Prompt seed list matches active features only
- Settings prompt dropdown shows only active templates

## Tests
- Prompt seed test updated
- `python -m pytest -q`

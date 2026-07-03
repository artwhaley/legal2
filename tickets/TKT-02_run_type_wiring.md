# TKT-02 — Run Type Wiring

## Goal

Wire `RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS` into the prompt system and task-role mapping
so the new merge function can call `run_nim_chat(..., run_type=..., messages=...)`.

---

## Depends On

- Nothing (run type constant is defined in `nim/prompts.py` alongside all other run types)

---

## Context

`run_nim_chat` needs three things to work with a new run type:

1. The constant exists in `nim/prompts.py` so `get_active_prompt(conn, run_type)` can
   find a prompt template.
2. The run type appears in `ALL_RUN_TYPES` so `seed_default_prompts` creates its
   prompt template row.
3. A default body exists in `DEFAULT_PROMPT_BODIES` so the seed has content.
4. The run type maps to a `ModelTaskRole` in `llm/task_roles.py` so the router picks
   the right model config.
5. Optional but recommended: an `LlmCallSite` entry in `llm/task_roles.py` so the
   call inventory knows about this site.

---

## Deliverables

### 1. `nim/prompts.py` — Add constant + wire run type

- Add the constant alongside the existing ones:
  ```python
  RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS = "evidence_ledger_synthesis"
  ```

- Add `RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS` to `ALL_RUN_TYPES` tuple.

- Add a default prompt body to `DEFAULT_PROMPT_BODIES`:
  ```python
  RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS: (
      "You are a legal evidence reviewer. The user supplies a ledger of evidence "
      "records. Analyze the ledger, identify themes, patterns, contradictions, "
      "and uncertainties. Return JSON only."
  ),
  ```

  This default body is a placeholder. The actual synthesis prompt is provided
  at call time via the `messages=` parameter (which bypasses `build_chat_messages`
  and the prompt body). But a non-empty default is required for:
  - Prompt seed (DB row creation)
  - Audit/log records (prompt_version metadata)
  - Future prompt-editing UI

### 2. `llm/task_roles.py` — Wire task role

- Import the constant from `nim.prompts`:
  ```python
  from message_evidence_workstation.nim.prompts import (
      ...,
      RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS,
  )
  ```

- Add to `RUN_TYPE_TO_TASK_ROLE`:
  ```python
  RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS: ModelTaskRole.WINDOWED_RESULT_MERGE,
  ```

- Add `LlmCallSite` entry (renumber to match your editor's auto-format):
  ```python
  LlmCallSite(
      "search.conversational_answer",
      "_run_evidence_ledger_window_merge",
      ModelTaskRole.WINDOWED_RESULT_MERGE,
      "workflow",
      run_type=RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS,
  ),
  ```

  This is added in this ticket but won't be used until TKT-04 creates the function.
  That's fine — the inventory can include forward-looking entries.

---

## Guard Rails

1. The default prompt body in `DEFAULT_PROMPT_BODIES` must be non-empty and
   parseable as valid text. It does not need to be a complete instruction — it
   only exists for DB seeding and audit metadata.
2. `ALL_RUN_TYPES` is a tuple, not a list. Add the new constant using the same
   tuple style already used in `nim/prompts.py`; do not convert it to a list.
3. The `ModelTaskRole` choice (`WINDOWED_RESULT_MERGE`) means the same model/user-facing
   role as the existing exhaustive window merge. This is expected: both are merge/synthesis
   calls that consume scanned window data.
4. Do not change `ModelRouter`, `NimClient`, or `run_nim_chat`.
5. Do not change the role mappings for existing run types.

---

## Acceptance Criteria

- `RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS` constant is importable from its canonical
  location.
- `ALL_RUN_TYPES` contains the new constant.
- `DEFAULT_PROMPT_BODIES` has a non-empty entry for the constant.
- `seed_default_prompts` creates a prompt template row for the new run type
  (verify by calling `get_active_prompt` with the new run type after seeding).
- `task_role_for_run_type(RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS)` returns
  `ModelTaskRole.WINDOWED_RESULT_MERGE`.
- `call_sites_for_run_type(RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS)` returns at least
  one entry.
- Existing run types are unaffected.

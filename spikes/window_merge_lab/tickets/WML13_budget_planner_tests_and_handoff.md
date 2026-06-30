# WML13 - Budget Planner Tests And Handoff

## Goal
Add regression tests and handoff notes for the synthesis budget planner.

## Depends On
- WML12

## Scope

Add or update smoke/unit tests for:

- Mode 1 selection when full estimates fit.
- Mode 2 selection when full output estimate exceeds budget.
- Mode 2 selection when full input estimate exceeds budget.
- No planner mode drops evidence records.
- Mode 1 prompt includes rich synthesis guidance.
- Mode 2 prompt includes compact preservation guidance.
- One-shot, hierarchical, rolling, and evidence-table strategies all invoke the planner.
- Hierarchical and rolling strategies persist one planner metric entry per LLM call.
- Prompts include:
  - `source_range_key`
  - `input_title`
  - `input_summary`
  - content-bearing title instructions
- Strategy output metrics include planner fields for all LLM-backed strategies.
- Evaluator can recover malformed provenance keys via hit IDs.

Update docs:

- `README.md` or `RECOMMENDATION.md`
- Explain the two planner modes.
- Explain that planner mode selection applies to all LLM-backed merge strategies, not only table+synthesis.
- Explain why refusal belongs before windowed search, not after it.
- Explain known gap: Mode 2 alone is insufficient for very large result sets (e.g. 500+ ranges → ~36K tokens output). The spike assumes compact direct synthesis fits every result set the front end allows through. Production will need either:
  - Hard limits that prevent result sets too large for compact direct synthesis
  - Or recursive/windowed synthesis of synthesis outputs (explicitly deferred from this spike)
- Explain future production work:
  - search-breadth gate before expensive windowed search
  - front-end warnings for broad queries
  - projected hit/window count before model calls

## Guardrails

- Do not write a production implementation plan that implies this spike is already production-ready.
- Do not recommend late-stage synthesis refusal.
- Do not introduce recursive/windowed synthesis as part of this stack.

## Acceptance Criteria

- Tests pass with:

```powershell
python -m pytest spikes\window_merge_lab\tests\test_smoke.py
```

- Documentation clearly says:
  - Mode 1 is rich direct synthesis.
  - Mode 2 is compact direct synthesis.
  - Mode 2 is the fallback, not a failure.
  - Too-broad query prevention belongs before expensive search execution.
- Handoff names remaining production risks and follow-up work.
- Handoff explicitly calls out that `deterministic_baseline` is excluded because it makes no LLM calls.

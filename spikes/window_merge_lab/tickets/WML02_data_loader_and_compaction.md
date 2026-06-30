# WML02 - Data Loader And Compaction

## Goal
Implement reusable input loading, response parsing, compaction, and validation helpers.

## Depends On
- WML01

## Scope
- Implement `data_loader.py`.
- Load rich and compact input JSON.
- Parse fenced JSON model responses.
- Extract:
  - `answer_summary`
  - `answer`
  - `answer_ranges`
  - `uncertainties`
  - coverage metadata
- Compact scan outputs into strategy-friendly records.
- Validate message IDs against exported window message ids.
- Count ranges per window.
- Provide helper APIs usable by both CLI and GUI.

## Guardrails
- Do not silently discard unparseable raw responses.
- Preserve raw response text alongside parsed data.
- Deterministic compaction is support machinery only, not final product answer.

## Acceptance Criteria
- Loader can read `inputs/school_scan_windows.json`.
- Loader returns six source windows.
- Loader reports parse status and answer-range count for each window.
- Invalid/missing IDs are reported in validation output.


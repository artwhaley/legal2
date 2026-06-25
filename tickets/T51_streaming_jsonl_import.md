# T51 - Streaming JSONL Import

## Goal
Stream normalized donor JSONL files line-by-line with batched inserts so import memory does not scale with message count, while preventing half-imported datasets from being treated as valid.

## Background
`_read_jsonl` buffers entire `source_threads.jsonl` and `messages.jsonl` before insert. Large donor dumps will spike RAM. Batched commits solve memory pressure, but they also require explicit failure semantics so a partially imported workspace is not accidentally opened as complete.

**Spec reference:** `04_pre_scale_hardening_spec.md` Section 5, Section D (format version validation)

## Depends On
- T61 (batch process logging foundation)

## Scope
- Replace `_read_jsonl` list accumulation with streaming iterators.
- Validate required fields per line; preserve file + line number in errors.
- Batched `executemany` inserts (chunk size around 1000) with commit per chunk.
- Add import validity state:
  - Mark dataset/workspace import as `loading` or `stale` before destructive reload begins.
  - Mark as `ready` only after all required files import and post-import index/session steps complete.
  - On failure, leave a clear failed/stale state with error details.
  - T55 must not enable dataset-dependent tabs for failed/stale imports.
- Progress callback: `(phase, lines_read, lines_written)` for UI consumers.
- Add `normalized_format_version` to `dataset.json`; validate on import (reject or warn on mismatch; document supported version constant).
- Post-import index rebuilds remain synchronous for this ticket but must accept progress callback hooks (FTS, spellfix, sessions narrated in T55).

## Guardrails
- Do not change normalized file contract field names beyond adding `normalized_format_version`.
- Do not drop existing validation error quality.
- Keep `reload` dataset semantics, but ensure reload failure does not masquerade as valid old/new data.

## Non-Goals
- Load Dataset tab UI (T55).
- Background index rebuild.
- Raw donor importers.

## Acceptance Criteria
- Peak import memory does not grow linearly with total line count (batch-size bounded).
- 100k-line generated fixture imports without OOM on typical analyst machine (`@pytest.mark.scale` acceptable).
- Malformed line still reports file + line number.
- Failed import leaves dataset/workspace marked failed or stale, never ready.
- `normalized_format_version` validated when present in `dataset.json`.

## Tests
- Import fixture dataset still passes.
- Test batched insert with multi-chunk small fixture.
- Failed import test proves ready state is not set and error is preserved.
- Optional scale test (marked) for large generated JSONL.
- `python -m pytest -q`

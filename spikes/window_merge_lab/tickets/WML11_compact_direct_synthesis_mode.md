# WML11 - Compact Direct Synthesis Mode

## Goal
Implement shared Mode 2 prompt behavior for preservation-first compact direct synthesis across all LLM-backed merge strategies.

## Depends On
- WML10

## Scope

Add a compact prompt profile for every LLM-backed prompt builder.

This includes:

- `build_one_shot_messages`
- `build_hierarchical_batch_messages`
- `build_rolling_synthesis_messages`
- `build_evidence_table_messages`

Mode 2 should be selected when Mode 1 is estimated to be too expensive or too close to budget. It is not an error and should not degrade evidence coverage.

For Mode 2, every prompt that carries evidence ranges should:

- Preserve every source range.
- Keep the answer narrative short.
- Keep range titles content-bearing.
- Use minimal range summaries.
- Use minimal display text.
- Avoid aggressive merging.
- Copy `source_range_key` values exactly.

For hierarchical or rolling prompts that carry interim syntheses, compact mode should preserve child range provenance and avoid summarizing away the range inventory.

## Prompt Requirements

The prompt must explicitly say:

- Navigation correctness is more important than rich prose.
- Do not drop ranges to save tokens.
- Do not merge separate conversations or separate topics.
- If fields must be short, shorten `answer`, `summary`, and `display_text` first.
- Keep `title` useful enough for a reviewer to understand the passage.
- Avoid generic labels like `School Discussion on March 24, 2022` when `input_title` or `input_summary` provides substance.

## Prompt Requirements — answer_format

Mode 2 always sets `"answer_format": "brief"`. The prompt should instruct the model to produce compact analysis: a short narrative, minimal per-range summaries, and truncated display text while preserving all range titles and IDs.

## Expected Output Shape

```json
{
  "answer_summary": "This search found many school-related discussions spanning preschool, Wildflower, co-op changes, and homeschooling.",
  "answer_format": "brief",
  "answer": "The results are preserved as a compact range inventory. Major themes include preschool attendance, school selection, Wildflower logistics, co-op instability, and homeschooling disputes.",
  "answer_ranges": [
    {
      "title": "Tummy aches and school attendance",
      "summary": "Tummy aches and attendance.",
      "date_description": "On February 21, 2022",
      "display_text": "Tummy aches and attendance",
      "hit_message_id": "...",
      "start_message_id": "...",
      "end_message_id": "...",
      "source_range_keys": ["..."]
    }
  ],
  "uncertainties": [],
  "coverage_summary": {
    "mode": "compact_direct_synthesis",
    "input_range_count": 230,
    "output_range_count": 230,
    "reason": "Compact mode selected to preserve all ranges within output budget."
  }
}
```

## Guardrails

- Do not add a refusal path.
- Do not sample ranges.
- Do not truncate provenance fields.
- Do not turn titles into date-only labels.
- Do not treat compact mode as lower-quality if it preserves ranges.

## Acceptance Criteria

- Mode 2 prompt is visibly different from Mode 1 for one-shot, hierarchical, rolling, and table+synthesis.
- Mode 2 prompt prioritizes range preservation over prose richness in every LLM-backed strategy.
- Mode 2 output instructions still require all range IDs and provenance keys in every LLM-backed strategy.
- Tests assert Mode 2 prompt contains compact-mode guidance.
- Tests assert Mode 2 still includes `input_title`, `input_summary`, and `source_range_key` whenever original evidence records are sent.

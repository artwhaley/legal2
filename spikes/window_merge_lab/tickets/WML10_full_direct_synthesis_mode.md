# WML10 - Full Direct Synthesis Mode

## Goal
Implement shared Mode 1 prompt behavior for rich direct synthesis across all LLM-backed merge strategies.

## Depends On
- WML09

## Scope

Update all LLM-backed merge prompt builders so they can receive a `SynthesisBudgetPlan` or prompt profile.

This includes:

- `build_one_shot_messages`
- `build_hierarchical_batch_messages`
- `build_rolling_synthesis_messages`
- `build_evidence_table_messages`

For Mode 1, every prompt that carries evidence ranges should:

- Include compact evidence records with:
  - `source_range_key`
  - `window_id`
  - `source_thread_id`
  - `input_title`
  - `input_summary`
  - `hit_message_id`
  - `start_message_id`
  - `end_message_id`
  - `date_description`
- Ask for a cohesive final answer.
- Preserve every input range.
- Allow light merging only when ranges clearly refer to the same conversation event.
- Require all represented `source_range_key` values in `source_range_keys`.
- Require content-bearing titles.
- Include useful `summary` and `display_text` fields.

For hierarchical or rolling prompts that carry interim syntheses instead of original scan windows, preserve existing `source_range_keys` and carry enough compact analysis context forward for the next call.

## Prompt Requirements

The prompt must communicate:

- The prior window-level title and summary are compact evidence context.
- The model may rewrite titles/summaries for cohesion.
- The model should not produce generic date-only titles when content clues exist.
- Good title example: `Tummy aches and school attendance`.
- Bad title example: `Conversation on January 21`.
- Range preservation is more important than making the answer short.

## Prompt Requirements — answer_format

Mode 1 always sets `"answer_format": "detailed"`. The prompt should instruct the model to produce full analysis with substantive titles, descriptive summaries, and a cohesive narrative answer.

## Expected Output Shape

```json
{
  "answer_summary": "...",
  "answer_format": "detailed",
  "answer": "...",
  "answer_ranges": [
    {
      "title": "Tummy aches and school attendance",
      "summary": "Olivia complained of stomach aches around school attendance...",
      "date_description": "On February 21, 2022",
      "display_text": "Tummy aches and reluctance to attend school",
      "hit_message_id": "...",
      "start_message_id": "...",
      "end_message_id": "...",
      "source_range_keys": ["..."]
    }
  ],
  "uncertainties": [],
  "coverage_summary": {
    "mode": "full_direct_synthesis",
    "input_range_count": 67,
    "output_range_count": 67
  }
}
```

## Guardrails

- Do not remove provenance fields.
- Do not remove compact analysis fields.
- Do not ask the model to infer semantic content from IDs alone.
- Do not instruct aggressive deduplication.

## Acceptance Criteria

- Mode 1 prompt includes compact analysis context for one-shot, hierarchical, rolling, and table+synthesis.
- Mode 1 prompt requires content-bearing titles in all LLM-backed strategies.
- Mode 1 prompt says light merging only for same-event records in all LLM-backed strategies.
- Prompt preview makes the selected mode visible.
- Tests assert Mode 1 prompt contains the expected preservation and title guidance.

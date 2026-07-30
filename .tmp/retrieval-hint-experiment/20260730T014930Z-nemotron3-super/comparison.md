# Retrieval hint investigation

Diagnostic comparison; this is not a statistical benchmark.

- Question: `When did we fight about school?`
- Frozen retrieval terms: `When, did, we, fight, about, school`
- Apples-to-apples validity: **False**
- Validity reasons:
  - censored-semantic returned a partial or failed result

| Arm | Strategy | Gold recall | Outside-suggestion final ranges | Window hash |
|---|---|---:|---:|---|
| semantic_ranges_censored | None | 0/7 | None | `370300a8ca88338cd2745d9022c005f5930234616b796361f1b9c344adfab05d` |
| semantic_ranges | multi_window_ledger | 0/7 | 0 | `370300a8ca88338cd2745d9022c005f5930234616b796361f1b9c344adfab05d` |
| terms_only | multi_window_ledger | 0/7 | 0 | `370300a8ca88338cd2745d9022c005f5930234616b796361f1b9c344adfab05d` |

## Exact returned results

### semantic_ranges_censored

The arm failed without a synthesized answer.

````json
{
  "code": "LEDGER_BIJECTION_FAILED",
  "details": {
    "completed_windows": 0,
    "end_message_id": "decipher_message_1:1203",
    "end_message_index": 6179,
    "range_index": 0,
    "reason": "reversed_in_supplied_message_order",
    "start_message_id": "decipher_message_1:1198",
    "start_message_index": 6184,
    "window_count": 2,
    "window_id": "w000001"
  },
  "message": "model evidence coverage is invalid",
  "request_id": "86f25081-6d5c-43aa-b191-b017767a2946",
  "retryable": false,
  "stage": "ledger"
}
````

### semantic_ranges

#### Synthesized answer

````text
There is no evidence in the provided message windows indicating when a fight about school occurred.
````

#### Answer summary

````text
The logs contain no relevant information about a school-related fight.
````

#### Complete returned evidence ledger

````json
[]
````

#### Diagnostics, processing, coverage, and usage

````json
{
  "strategy": "multi_window_ledger",
  "uncertainties": [
    "No evidence ranges were identified in windows w000001 and w000002 to answer the question."
  ],
  "coverage": {
    "evidence_range_count": 0,
    "message_count": 12402,
    "window_count": 2
  },
  "retrieval_diagnostics": {
    "final_ranges_outside_suggestions": 0,
    "final_ranges_overlapping_suggestions": 0,
    "mode": "semantic_ranges",
    "query_count": 6,
    "raw_hit_count": 600,
    "selected_suggestion_message_count": 40,
    "suggestion_range_count": 40,
    "suggestions_without_final_evidence": 40,
    "unique_candidate_message_count": 479,
    "used_ranges_outside_suggestions": 0,
    "used_ranges_overlapping_suggestions": 0
  },
  "ledger_processing": {
    "compaction_applied": false,
    "compaction_group_calls": 0,
    "compaction_levels": 0,
    "direct_synthesis_input_tokens": 668,
    "synthesis_usable_input_tokens": 982118
  },
  "usage": {
    "cost_complete": false,
    "currency": "USD",
    "estimated_cost": null,
    "input_tokens": 1131118,
    "output_tokens": 430,
    "source": "provider_reported"
  }
}
````

### terms_only

#### Synthesized answer

````text
The provided message windows contain no evidence of a fight about school, so the timing cannot be determined.
````

#### Answer summary

````text
No evidence of a school-related fight is present in the logs, leaving the timing unknown.
````

#### Complete returned evidence ledger

````json
[]
````

#### Diagnostics, processing, coverage, and usage

````json
{
  "strategy": "multi_window_ledger",
  "uncertainties": [
    "No evidence found regarding a fight about school."
  ],
  "coverage": {
    "evidence_range_count": 0,
    "message_count": 12402,
    "window_count": 2
  },
  "retrieval_diagnostics": {
    "final_ranges_outside_suggestions": 0,
    "final_ranges_overlapping_suggestions": 0,
    "mode": "terms_only",
    "query_count": 6,
    "raw_hit_count": 0,
    "selected_suggestion_message_count": 0,
    "suggestion_range_count": 0,
    "suggestions_without_final_evidence": 0,
    "unique_candidate_message_count": 0,
    "used_ranges_outside_suggestions": 0,
    "used_ranges_overlapping_suggestions": 0
  },
  "ledger_processing": {
    "compaction_applied": false,
    "compaction_group_calls": 0,
    "compaction_levels": 0,
    "direct_synthesis_input_tokens": 668,
    "synthesis_usable_input_tokens": 982118
  },
  "usage": {
    "cost_complete": false,
    "currency": "USD",
    "estimated_cost": null,
    "input_tokens": 1127921,
    "output_tokens": 607,
    "source": "provider_reported"
  }
}
````


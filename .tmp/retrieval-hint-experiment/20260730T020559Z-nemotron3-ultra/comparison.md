# Retrieval hint investigation

Diagnostic comparison; this is not a statistical benchmark.

- Question: `When did we fight about school?`
- Frozen retrieval terms: `fight, school, fight about school`
- Apples-to-apples validity: **False**
- Validity reasons:
  - censored-semantic returned a partial or failed result
  - full-semantic returned a partial or failed result
  - terms-only returned a partial or failed result

| Arm | Strategy | Gold recall | Outside-suggestion final ranges | Window hash |
|---|---|---:|---:|---|
| semantic_ranges_censored | None | 0/7 | None | `370300a8ca88338cd2745d9022c005f5930234616b796361f1b9c344adfab05d` |
| semantic_ranges | None | 0/7 | None | `370300a8ca88338cd2745d9022c005f5930234616b796361f1b9c344adfab05d` |
| terms_only | None | 0/7 | None | `370300a8ca88338cd2745d9022c005f5930234616b796361f1b9c344adfab05d` |

## Exact returned results

### semantic_ranges_censored

The arm failed without a synthesized answer.

````json
{
  "code": "LEDGER_BIJECTION_FAILED",
  "details": {
    "completed_windows": 1,
    "declared_thread_id": "julie_kramer",
    "end_message_id": "decipher_message_1:3397",
    "range_index": 0,
    "reason": "unknown_or_blank_value",
    "start_message_id": "decipher_message_1:3370",
    "window_count": 2,
    "window_id": "w000002"
  },
  "message": "model evidence coverage is invalid",
  "request_id": "83bb3217-6f54-4152-b0e6-34d61782f932",
  "retryable": false,
  "stage": "ledger"
}
````

### semantic_ranges

The arm failed without a synthesized answer.

````json
{
  "code": "LEDGER_BIJECTION_FAILED",
  "details": {
    "completed_windows": 1,
    "declared_thread_id": "julie_kramer",
    "end_message_id": "decipher_message_1:3390",
    "range_index": 0,
    "reason": "unknown_or_blank_value",
    "start_message_id": "decipher_message_1:3370",
    "window_count": 2,
    "window_id": "w000002"
  },
  "message": "model evidence coverage is invalid",
  "request_id": "05b5cc1f-bac7-4fb1-97f6-b7284c700792",
  "retryable": false,
  "stage": "ledger"
}
````

### terms_only

The arm failed without a synthesized answer.

````json
{
  "code": "LEDGER_BIJECTION_FAILED",
  "details": {
    "completed_windows": 0,
    "end_message_id": "decipher_message_1:2720",
    "end_message_index": 4662,
    "range_index": 0,
    "reason": "reversed_in_supplied_message_order",
    "start_message_id": "decipher_message_1:2715",
    "start_message_index": 4667,
    "window_count": 2,
    "window_id": "w000001"
  },
  "message": "model evidence coverage is invalid",
  "request_id": "c7aaa8b5-b95d-4624-b839-56e0a0f38f31",
  "retryable": false,
  "stage": "ledger"
}
````


# Retrieval hint investigation

Diagnostic comparison; this is not a statistical benchmark.

- Question: `When did we fight about school?`
- Frozen retrieval terms: `fight, school, when, we`
- Apples-to-apples validity: **False**
- Validity reasons:
  - terms-only and full-semantic arms are both required
  - terms-only returned a partial or failed result

| Arm | Strategy | Gold recall | Outside-suggestion final ranges | Window hash |
|---|---|---:|---:|---|
| terms_only | None | 0/7 | None | `7b45af86f6c4d8a1316d09fbea2208068ac6b2c84bcac7241d56c9af2b799c16` |

## Exact returned results

### terms_only

The arm failed without a synthesized answer.

````json
{
  "code": "PROVIDER_REJECTED",
  "details": {
    "completed_windows": 0,
    "window_count": 2
  },
  "message": "provider returned HTTP 400",
  "request_id": "ccb68fa5-0e53-4409-9e5f-b3b9a86b8d97",
  "retryable": false,
  "stage": "provider"
}
````


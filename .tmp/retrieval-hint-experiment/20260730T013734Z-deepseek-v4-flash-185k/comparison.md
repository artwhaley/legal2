# Retrieval hint investigation

Diagnostic comparison; this is not a statistical benchmark.

- Question: `When did we fight about school?`
- Frozen retrieval terms: `fight about school, school fight, argue about school`
- Apples-to-apples validity: **False**
- Validity reasons:
  - terms-only and full-semantic arms are both required
  - terms-only returned a partial or failed result

| Arm | Strategy | Gold recall | Outside-suggestion final ranges | Window hash |
|---|---|---:|---:|---|
| terms_only | None | 0/7 | None | `33eb93b7f995ca0e1ca0c3fdd6d621683734370d211c41fec6a5e690bd67a1da` |

## Exact returned results

### terms_only

The arm failed without a synthesized answer.

````json
{
  "code": "PROVIDER_REJECTED",
  "details": {
    "completed_windows": 0,
    "window_count": 6
  },
  "message": "provider returned HTTP 529",
  "request_id": "07d7f7c7-cc19-47e5-8e30-e1dd5200b010",
  "retryable": false,
  "stage": "provider"
}
````


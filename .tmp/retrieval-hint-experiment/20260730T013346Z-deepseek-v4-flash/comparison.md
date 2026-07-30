# Retrieval hint investigation

Diagnostic comparison; this is not a statistical benchmark.

- Question: `When did we fight about school?`
- Frozen retrieval terms: `fight about school, school`
- Apples-to-apples validity: **False**
- Validity reasons:
  - terms-only and full-semantic arms are both required
  - terms-only returned a partial or failed result

| Arm | Strategy | Gold recall | Outside-suggestion final ranges | Window hash |
|---|---|---:|---:|---|
| terms_only | None | 0/7 | None | `f14866196d35d40032419f12472a06ac81b8cd7242b440e6bd6748912a52d69b` |

## Exact returned results

### terms_only

The arm failed without a synthesized answer.

````json
{
  "code": "PROVIDER_REJECTED",
  "details": {
    "completed_windows": 0,
    "window_count": 3
  },
  "message": "provider returned HTTP 529",
  "request_id": "4e9b67c2-1ede-44fa-8b82-92417c66ed55",
  "retryable": false,
  "stage": "provider"
}
````


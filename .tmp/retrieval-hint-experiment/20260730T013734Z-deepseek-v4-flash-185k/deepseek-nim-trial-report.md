# DeepSeek NVIDIA NIM trial report

Question: `When did we fight about school?`

Model routing: every server-owned model operation used
`deepseek-ai/deepseek-v4-flash`.

This trial did not produce synthesized answers or evidence ledgers. NVIDIA's
hosted trial endpoint did not remain available long enough to complete the
`terms_only` arm, so the semantic arms were not submitted as if they could
produce a valid comparison.

## Uncapped 500K-profile trial

Artifacts:

- Directory:
  `.tmp\retrieval-hint-experiment\20260730T013346Z-deepseek-v4-flash`
- Frozen plan:
  `40e160dd-9dcc-4561-8c1f-232a0dbbb984`
- Extracted retrieval terms:
  `fight about school`, `school`
- Planned windows: 3
- Window-plan hash:
  `f14866196d35d40032419f12472a06ac81b8cd7242b440e6bd6748912a52d69b`
- Debug capture:
  `C:\Users\artwh\.message_evidence_server\debug-captures\20260730T013346Z-6250c608d501.jsonl`

Two explicitly initiated `terms_only` attempts failed on the first window.
Each received the same provider response:

```json
{
  "message": "Service temporarily overloaded",
  "type": "Overloaded",
  "code": 529
}
```

The first failed in 11.2 seconds and the spaced retry failed in 10.7 seconds.
The failures are preserved separately as
`terms-only-attempt-1-result.json` and `terms-only-result.json`.

## Conservative 185K extraction-ceiling trial

Artifacts:

- Directory:
  `.tmp\retrieval-hint-experiment\20260730T013734Z-deepseek-v4-flash-185k`
- Frozen plan:
  `4872d9d8-77ab-4660-b82b-e6da470a4964`
- Extracted retrieval terms:
  `fight about school`, `school fight`, `argue about school`
- Effective target per window:
  166,500 tokens after applying 90% utilization
- Planned windows: 6
- Window-plan hash:
  `33eb93b7f995ca0e1ca0c3fdd6d621683734370d211c41fec6a5e690bd67a1da`
- Debug capture:
  `C:\Users\artwh\.message_evidence_server\debug-captures\20260730T013734Z-10c795bd94b9.jsonl`

The first correctly capped attempt completed window 1 with 156,129 provider-
reported input tokens in 11.6 seconds. NVIDIA then returned HTTP 529 on window
2, and the request failed after 19.4 seconds with 1/6 windows complete. This is
preserved as `terms-only-before-529-backoff-result.json`.

One final attempt explicitly configured HTTP 529 as retryable for the
window-extraction and ledger-synthesis operations. It used three total attempts
with visible 30-second and 60-second retry waits. All three attempts on window
1 returned HTTP 529. The request failed after 99.3 seconds with 0/6 windows
complete. This is the current `terms-only-result.json`.

No runner-level retry, provider fallback, malformed-output repair, or silent
failure handling was used. Every provider failure and retry wait is present in
the result artifacts and debug capture.

## DeepSeek V4 Pro availability probe

The authenticated NVIDIA model catalog also exposed
`deepseek-ai/deepseek-v4-pro`. A direct two-line structured-output probe with a
64-token output ceiling failed to return response headers within 120 seconds.
Because trivial work did not complete, the large-corpus experiment was not
submitted to that pool.

## Conclusion

DeepSeek V4 Flash demonstrated that a 156K-token extraction call is accepted
and can complete quickly, but NVIDIA's hosted trial pool could not sustain this
workload. DeepSeek V4 Pro was unavailable even for a trivial probe. These are
provider-capacity results, not evidence-quality results.

Both debug captures stopped cleanly with zero pending records and no writer
failure. The active server configuration was restored from known-good version
25 as version 37: GLM-5.2 owns all five model operations, semantic retrieval is
active, the extraction ceiling is unset, and HTTP 529 is not retained in the
retry policy.

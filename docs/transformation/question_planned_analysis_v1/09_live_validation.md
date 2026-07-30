# Live validation

## Purpose

Prove the production-shaped pipeline can:

- create a genuine analysis plan;
- use that same plan for at least six GLM extraction windows;
- preserve high-recall candidate evidence;
- synthesize an answer that distinguishes responsive conflicts from
  cooperative on-topic noise;
- expose complete ledger dispositions, findings, rejected ranges, cost, and
  timing.

This is one diagnostic run, not a statistical model benchmark.

## Preconditions

Do not begin until all deterministic gates pass.

Verify and record:

- repository environment is active;
- current server configuration is schema v4;
- planner, extraction, compaction, and synthesis are assigned to the intended
  GLM 5.2 model profile through admin;
- provider/model/context/reasoning/temperature/prompt/output settings;
- semantic retrieval mode and embedding geometry;
- selected EVW revision 4 contains the established 12,402-message working
  corpus and has compatible local embeddings;
- no unrelated live request is active;
- exact debug capture is stopped before starting a fresh session;
- server and client logs have explicit paths.

Never print or copy API keys.

## Temporary window configuration

The run must produce at least six extraction windows so synthesis sees a noisy
multi-window ledger.

If active production tuning would produce fewer than six:

1. record the complete current active configuration/version;
2. create a draft;
3. lower only the explicit window-utilization/operation input setting required
   to produce at least six deterministic windows;
4. validate and activate it through the normal control path;
5. record the resulting calculated target;
6. restore the original setting through a new activated version after the run.

Do not alter model, prompt, retrieval policy, corpus, or question to force an
outcome. Do not hand-construct windows.

## One authorized run

Use the exact question:

```text
Show me fights about school.
```

Execute one ordinary Python test-client conversational action:

1. `POST /v1/conversational-plan`;
2. one query-embedding workload;
3. exact local semantic lookup in revision 4;
4. `POST /v1/conversational-analysis`;
5. every planned extraction window;
6. direct synthesis or loudly reported compaction;
7. terminal result.

Start fresh exact debug capture immediately before planning. Stop and flush it
immediately after the terminal result.

Do not:

- repeat the run automatically;
- switch provider/model;
- alter the plan;
- censor or add retrieval hits;
- repair malformed IDs;
- call a private synthesis endpoint;
- treat a partial result as complete.

Existing configured provider retries may occur and must be reported.

## Artifacts

Write one timestamped directory under:

`.tmp/question-planned-analysis-live/`

Include:

- redacted run manifest;
- exact plan response;
- retrieval query/geometry/rank metadata;
- request metadata and window-plan hash;
- per-window timing/status/accepted/rejected/normalized counts;
- synthesis preflight and compaction status;
- complete final result JSON;
- human-readable Markdown containing the actual answer, findings, full ledger,
  dispositions, rationales, validation diagnostics, uncertainties, usage, and
  timing;
- debug-capture path and stopped/flushed state;
- server/client stdout/stderr paths;
- restored configuration version.

Do not copy API keys or entire corpus messages into the manifest/report. Exact
content remains in the controlled debug capture and ordinary result artifacts.

## Review

The seven provisional-positive dates used only for diagnostic review are:

```text
2023-03-28
2023-11-13
2024-06-26
2024-07-10
2025-07-16
2025-08-04
2026-07-01
```

These values must never appear in production prompts, provider payload
templates, validators, or deterministic product tests.

Report:

- which provisional positives extraction found;
- which became `direct_evidence`;
- which findings cited them;
- every extraction candidate classified `useful_context`;
- every extraction candidate classified `not_responsive`;
- whether cooperative school planning/logistics was incorrectly presented as
  a fight;
- whether any direct conflict was demoted or omitted from the answer;
- evidence found outside retrieval suggestions;
- partial-range status and exact non-content reason codes;
- compaction status;
- provider retries/failures;
- complete provider-reported/estimated usage and elapsed time.

The desired quality result is:

- high candidate recall;
- cooperative/noise ranges retained in the ledger but not misrepresented;
- answer findings supported by direct range IDs;
- all validation limitations visible.

If the model does not meet this, preserve the result and report the concrete
failure. Do not tune and rerun inside this gate.

## External failure

If credentials are unavailable or the configured provider remains externally
unavailable after its already configured attempts:

- complete every local ticket/gate;
- preserve the exact provider error and request ID;
- stop processes and capture cleanly;
- record Gate K as the sole external blocker;
- do not silently select another model/provider.

## Cleanup

After the run:

- stop and flush debug capture;
- restore temporary window settings;
- stop unnecessary server/client/runner processes;
- verify no bound request remains;
- verify EVW hash/size and sidecars were not unexpectedly modified;
- run final deterministic regression, compile, package boundary, and
  `git diff --check`;
- update execution log and closeout.


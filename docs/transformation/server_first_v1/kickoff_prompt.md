# Server-First V1 Executor Kickoff

You are the execution agent for the repository at:

`C:\Users\artwh\OneDrive\Documents\legal2`

Implement the complete Server-First V1 transformation specified in:

`C:\Users\artwh\OneDrive\Documents\legal2\docs\transformation\server_first_v1\README.md`

Before editing anything:

1. Read the repository `AGENTS.md` in full.
2. Read every document listed in the packet README, in its specified order.
3. Inspect the current worktree and record the baseline required by ticket `SFV1-000`.
4. Treat the packet as the authoritative product and architecture specification for this phase. Do not substitute older transformation documents when they conflict with it.

Execute tickets `SFV1-000` through `SFV1-901` in dependency order. Complete each ticket's implementation, tests, and acceptance evidence before beginning a dependent ticket. Maintain `execution_log.md` as you work.

This phase is a deliberate clean break. Its non-negotiable shape is:

- The FastAPI server owns all provider calls, prompts, model selection, token budgeting, whole-versus-windowed conversational orchestration, window construction, evidence-ledger reduction and synthesis, embedding batching, retry policy, concurrency controls, accounting, and operational visibility.
- The server exposes exactly three product endpoints: `POST /v1/keyword-expansion`, `POST /v1/conversational-analysis`, and `POST /v1/embeddings`. Do not retain or add a public capabilities endpoint or compatibility product routes.
- The server never opens, receives, or persists an `.evw` file. User corpus content is request-local and must not be stored in the server control database or logs.
- The server has a real browser-based admin interface served by FastAPI. Do not build a Qt admin application, SPA, Node frontend, or decorative dashboard.
- A fresh server starts loopback in explicit admin bootstrap mode; product routes fail `CONFIGURATION_REQUIRED` until first valid activation. A corrupt prior active configuration aborts startup.
- Every meaningful server-side decision is configurable or inspectable in that admin interface exactly as specified. Prompts are editable. Request and response schemas are versioned in code and visible but not runtime-editable.
- Conversational analysis is one public operation. Whole-corpus execution, window extraction, evidence-ledger reduction, and final synthesis are internal server stages, not separate public product modes.
- Embedding callers may submit the complete required message set. The server validates the request, batches it internally, runs bounded concurrent provider calls, and streams ordered progress and results.
- Persist only the packet's append-only content-free usage records. Every provider attempt must be accounted before retry/success; never persist corpus, questions, prompts, model output, evidence, vectors, or user history on the server.
- The Python client remains only as a temporary integration harness. Modify it solely where tickets `SFV1-800` through `SFV1-803` authorize changes. It owns `.evw`, working-corpus selection, local FTS5, local vector lookup, and persistence. It must not choose models, orchestration paths, provider batch sizes, retry policies, or prompt variants.
- Do not modify Flutter or the `.evw` schema in this phase.
- Authentication, billing, subscriptions, and end-user BYOK are explicitly deferred. Until authentication exists, enforce the packet's loopback-only deployment rule.
- Do not add silent fallbacks, response-shape defaults, hidden retries, silent repair, arbitrary truncation, fake progress, compatibility shims, or placeholder production behavior. Fail noisy with the original cause preserved.

Make all required dependency changes and run all automated verification yourself. Do not hand dependency installation, test execution, migrations, server startup, or fixture preparation back to the user.

Preserve unrelated user changes in the dirty worktree. Never expose secrets in logs, test output, documentation, or source control. Do not commit, push, or deploy unless separately instructed.

Continue autonomously until every local acceptance gate in `07_acceptance_gates.md` passes. Run the live-provider gate if usable provider credentials are already available through the approved configuration path. If credentials are unavailable, complete every non-live gate and record the live gate as the only unexecuted external validation; do not fabricate success.

Stop before completion only for a genuine blocker requiring user authority, unavailable external credentials needed for the sole remaining live test, or a contradiction that cannot be resolved from the packet and repository. Before stopping, exhaust safe in-scope diagnosis, record the exact blocker and evidence in `execution_log.md`, and report the smallest decision or input required.

At completion, create `docs/transformation/server_first_v1/closeout_report.md` containing:

- every ticket and its disposition;
- every acceptance gate, exact command, and result;
- the final three-route API surface;
- the final admin URL and startup command;
- the Python harness startup command and manual end-to-end test sequence;
- configuration migration results with secrets redacted;
- deleted legacy paths and proof no production references remain;
- any intentionally deferred work, limited to the packet's stated exclusions.

Begin now with `SFV1-000`.

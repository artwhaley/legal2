# Message Evidence Workstation — Server-First V1

The FastAPI server owns provider calls, prompts, model selection, accounting,
conversation orchestration, evidence-ledger synthesis, embedding batching,
retries, concurrency, usage accounting, and operational visibility. The
temporary Python client owns the local EVW, working-corpus scope, FTS5,
sqlite-vec, streamed progress, and local history.

## Start the server

```powershell
.\.venv\Scripts\python.exe -m server
```

Open [http://127.0.0.1:8710/admin/](http://127.0.0.1:8710/admin/) to complete
the loopback bootstrap configuration. Until a valid version is activated,
the four product routes return `CONFIGURATION_REQUIRED`.

Product routes:

- `POST /v1/keyword-expansion`
- `POST /v1/conversational-plan`
- `POST /v1/conversational-analysis`
- `POST /v1/embeddings`

FastAPI docs/OpenAPI and the old v2/capabilities/internal product routes are
disabled. The server stores only encrypted provider secrets, immutable
configuration/audit records, and append-only content-free usage records.

## Start the temporary Python EVW harness

```powershell
.\.venv\Scripts\python.exe -m message_evidence_workstation.app `
  --db C:\path\to\workspace.evw
```

Do not pass `--dataset` when opening an existing V15 EVW; that option imports
a normalized source dataset and builds a new working corpus.

For question-planned conversational analysis, the client requests one
server-generated analysis plan, embeds its returned retrieval queries through
the server in one workload, performs local EVW vector lookup, and submits the
complete scoped conversation plus candidate IDs/ranks/distances. It consumes
the server's NDJSON analysis stream and never chooses provider models,
prompts, windows, retries, RRF policy, or server batch sizes.

Flutter server integration and further EVW schema changes are excluded from
this server-first phase; the existing read-only Flutter V15 viewer remains the
compatibility proof. Earlier transformation folders are historical evidence.
For question planning, unified extraction/ledger/synthesis, partial range
validation, and ledger compaction, the authoritative execution packet is
`docs/transformation/question_planned_analysis_v1/`.

The earlier visual acceptance sequence is in
`docs/transformation/server_first_v1/manual_test.md`. Dependency installation,
automated tests, release builds, and native probes are executor work, not user
test steps.

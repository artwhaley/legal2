# Closeout Ticket Stack

Execute sequentially unless a ticket explicitly says otherwise. Every ticket
must leave its targeted gate green. Do not postpone deletion tickets until
after acceptance; absence of vestigial paths is part of correctness.

## CLS-000 — Freeze baseline and test data

Record git state, current failures, current v12/v13 EVW inventories, canonical
row counts, excluded-table counts, active corpus/index state, WAL sizes, and all
client-local model/embedding and dataset-only search call sites. Create copied
fixtures with two threads and sentinel text inside/outside a limited corpus.
Never mutate the user's only EVW.

Done when `closeout_execution_log.md` contains the baseline and fixture hashes.

## CLS-101 — Define v14 DDL and validators

Implement the exact v14 contract in `01_evw_v14_and_scope_contract.md`. Remove
schema creation by incremental ALTER/compatibility probing. Fresh creation runs
one authoritative DDL and strict validator. Add table/column/index/FK/check
tests, excluded-table tests, singleton dataset tests, and conversation scope
provenance tests.

Dependencies: CLS-000.

## CLS-102 — Implement WorkspaceStore and OS lock

Add the held sidecar OS lock, dedicated writer thread, serialized transaction
queue, scoped read-only readers, explicit checkpoint APIs, and deterministic
shutdown. Replace `AppContext.conn` with `AppContext.workspace`. Convert small
repository/UI writes first and add second-process lock, crash-release, reader,
writer serialization, blocked checkpoint, and clean-close tests.

Dependencies: CLS-101.

## CLS-103 — Explicit compact-copy migration tool

Implement v12/v13-to-v14 migration as a command/tool outside runtime open.
Preserve selected canonical data and visible history, omit excluded data,
create the v14 corpus candidate, safely repack only complete/validated vectors,
validate, and leave the source/backup untouched. Runtime clients reject old
versions and contain no old-schema branch.

Dependencies: CLS-101, CLS-102.

## CLS-104 — Working-corpus service and active-scope resolver

Replace `v13_repositories.py` with production-named v14 repositories/services.
Implement immutable definitions, preview, exact token count, over-limit result,
membership build, activation, stale marking, content revision, index state, and
required scope types. Add the Python Search Corpus panel and default-under-limit
import flow. Do not build indexes yet beyond test fakes.

Dependencies: CLS-102.

## CLS-105 — Scope FTS5 and spellfix

Recreate lexical indexes with corpus/generation identity. Rewrite every FTS,
expanded-term, spellfix, grouping, detail, pagination, hint, and search-worker
signature to require `NarrowedSearchScope`. Delete dataset-only wrappers.
Build/activate FTS and spellfix sequentially and record ready states.

Dependencies: CLS-104.

## CLS-106 — Scope transcripts, windows, and evidence validation

Rewrite transcript loading, budget statistics, window planning, message-order
lookup, hints, range validation, and citation checks to join active membership.
Date narrowing applies after membership. Remove raw dataset-only entrypoints
from all search/conversational modules.

Dependencies: CLS-105.

## CLS-107 — Scope vectors and embedding jobs

Replace dataset/model partitions with required model/corpus/generation
partitions. Replace dataset embedding metadata/BLOB fallback with
`working_corpus_index`. Refactor indexing into read batch -> remote call stub ->
writer batch, with complete resume/error/ready state. Rewrite KNN SQL and search
APIs to require scope. At this ticket use deterministic injected embedding
responses; do not retain local model execution.

Dependencies: CLS-104, CLS-102.

## CLS-201 — Isolate server and API v2

Move providers, model errors/types/roles, and embedding execution wholly under
`server/`. Implement validated startup, API v2 contracts/capabilities/error
envelope, request limits, prompt-set v2, and the seven endpoints. Delete v1 and
legacy merge/planner prompts/endpoints. Add fake-provider, malformed-output,
oversize, order, logging-redaction, wheel-content, and package-isolation tests.

Dependencies: CLS-000. May be developed after CLS-101 while CLS-102–107 proceed,
but must merge before CLS-202.

## CLS-202 — Remote-only Python gateway and settings purge

Replace resolver/optional gateway with injected `RemoteGateway`. Reduce client
settings and Settings UI to server/planning/client fields. Delete client
provider/model/prompt/retry/local-embedding code and hidden controls. Add
gateway contract, exact-one-attempt, outage, incompatible-capabilities, and
static forbidden-import tests.

Dependencies: CLS-201.

## CLS-203 — ClientWorkflowService and lexical/vector parity

Implement the single orchestration service. Wire FTS, keyword-expanded FTS,
embedding build, and embedding search to scoped local operations plus API v2.
Convert Home, Search Corpus, Settings, Simple Search, import, and embedding UI
to WorkspaceStore/services. Remove independent writable connections.

Dependencies: CLS-105, CLS-107, CLS-202.

## CLS-204 — Remote-only conversational path

Retarget whole transcript, retrieval terms, window scan, and evidence-ledger
synthesis through the gateway. Delete generic planner/tool-runner/synthesis and
bounded merge paths. Enforce frozen scope, returned-ID validation, generation
recheck, and one-transaction visible-history persistence. Convert
ConversationalTab to `ClientWorkflowService` only.

Dependencies: CLS-106, CLS-202, CLS-203.

## CLS-205 — Complete writer conversion and dead-code deletion

Convert evidence, artifacts, formatting, transcript annotations, imports,
settings-backed workspace writes, and every worker to WorkspaceStore. Remove
raw client writer constructors, optional corpus keys, old migrations/exports,
compatibility shims, and obsolete tests/modules listed in the contract. Run AST
checks proving one writer and no client-local provider/model/embedding route.

Dependencies: CLS-203, CLS-204.

## CLS-301 — Flutter v14 read-only viewer

Split the probe from `main.dart`, add the v14 database reader and one viewer
screen, full/active toggle, thread list, paged transcript, explicit refresh,
file selection, and visible errors. Add widget/database/no-write tests. Keep the
release probe as `--probe` and update native hashes/build packaging.

Dependencies: CLS-101, CLS-103, CLS-104.

## CLS-401 — Cross-process and scope-leak integration gate

Run a fake API v2 server as a real subprocess and a headless Python client
workflow against the sentinel v14 fixture. Prove local FTS, remote embeddings,
local KNN, keyword expansion, and both conversational modes. Assert every
request/result contains only active/date-narrowed member IDs and text. Run the
Flutter viewer/probe against the same file while the Python writer is open and
after clean close.

Dependencies: CLS-205, CLS-301.

## CLS-402 — Production-shape closeout

Fix all regressions, including the existing chunk-calibration failure. Remove
tests for deleted architecture and replace them with target-contract tests. Run
every gate in `05_acceptance_and_closeout.md`, migrate a copy of the real EVW,
inspect it in Flutter, run all five Python search workflows, verify WAL/lock/
logs/package contents, and write `closeout_report.md` with exact evidence.

Dependencies: CLS-401.

Done means every required gate passes with no skip/xfail for an in-scope path
and the forbidden-surface scan is empty.

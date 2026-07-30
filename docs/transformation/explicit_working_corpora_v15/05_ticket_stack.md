# Authoritative Ticket Stack

Execute in dependency order. Breaking v14/obsolete tests is expected. Do not
preserve removed architecture for compatibility.

## EWC15-000 - Baseline and contact-surface inventory

Read this packet, `AGENTS.md`, dirty worktree, current schema/repositories,
embedding/vector/cache code, evidence blocks/slots/rendering, migration, Python UI,
Flutter, tests, and current fixtures.

Create `execution_log.md`. Record:

- branch/upstream/commit and dirty files without reverting;
- baseline compile/test/analyze results;
- all active/implicit corpus references;
- every mutable membership/index call;
- all vector/profile/version/partition tables and code;
- every evidence slot/origin/association contact surface;
- v14 fixture corpus, vector, evidence, history, WAL, and integrity inventory.

Gate: complete inventory; no unexplained mutation.

## EWC15-100 - Canonical v15 schema

Implement file 01 exactly: named corpora, immutable revisions/definition/
membership, revision indexes, sparse cache geometry/artifacts, exact evidence message
ranges/associations, conversation revision provenance, version checks, indexes,
constraints, immutability triggers, and removal of destructive canonical
reimport.

Runtime rejects v12-v14 without writing. Fresh v15 validator introspects all
required/forbidden structures.

Gate: schema tests pass; no old active/vector/slot storage remains.

## EWC15-110 - Explicit v12/v13/v14-to-v15 migration

Implement file 03 migration, including corpus-to-revision conversion, lexical
reconstruction, sparse vector collapse, explicit discard, positional-evidence
dry-run/map, history/provenance preservation, atomic file behavior, and strict
post-validation.

Tests include:

- multiple ready/stale/failed old corpora;
- old active value ignored;
- overlapping duplicate vectors collapsed;
- old profile/model identity ignored and absent from the v15 target;
- inconsistent retained vector geometry fails;
- conflicting duplicate vector fails;
- explicit discard;
- evidence with corpus map;
- evidence with canonical-thread map;
- missing/ambiguous/invalid map failure;
- conversations/citations;
- interrupted/same-path/separate-path;
- unchanged source hashes.

Gate: migration matrix passes and outputs pass v15 verifier.

## EWC15-200 - Typed corpus/revision repository

Implement exact projections, APIs, errors, immutable scope, pointer ownership,
draft editing, list/readiness validation, and no-fallback behavior from file
02. Remove old activation/get-scope/mutable-definition APIs.

Gate: repository tests cover every state/error and static scan finds no removed
runtime symbol.

## EWC15-210 - Build, index, and publication lifecycle

Implement deterministic build, lexical indexing, ready-unpublished state,
evidence compatibility assessment, explicit exclusions, atomic publication,
historical revision preservation, and derived-index repair rules.

Tests prove:

- A revision cannot mutate after build starts;
- A1 remains unchanged while A2 builds/publishes;
- failed A2 leaves A1 current;
- concurrent pointer change makes A2 publication fail base-changed;
- corpus B remains untouched;
- empty/768000/768001 behavior;
- canonical mismatch stales scope;
- compatible block associations carry;
- incompatible blocks block publication until exact exclusions;
- no block/range is modified.

Gate: lifecycle, transaction, lock, and WAL tests pass.

## EWC15-300 - Sparse embedding artifact service

Replace corpus-partitioned vec0 storage with one local cache-geometry row and
immutable hash-keyed artifacts.
Implement exact input hashing, cache-hit/miss planning, hash deduplication,
streamed missing-only server workload, short commits, interruption/resume,
coverage validation, deterministic chunk hashes, explicit whole-cache clearing,
and exact revision-scoped scalar-distance SQL.
Remove profile/model/version from local result types, search arguments, SQL,
readiness state, and UI. Existing opaque wire fields remain transport-only.

Pin and verify sqlite-vec v0.1.9 in Python and the Flutter Windows native
artifact/checksum.

Tests prove:

- no artifact exists before explicit build;
- no content-free handshake or expected-profile field is sent;
- A embeds only A;
- overlapping B sends only misses;
- A2 with ten new messages sends at most those ten and zero when B already
  cached them;
- same text/hash deduplicates;
- identical message and chunk text shares the same artifact;
- exact text change misses;
- explicit clear atomically removes every vector/cache-geometry row, marks all
  embedding coverage missing, and preserves chunks/lexical/user data;
- only embedding-specific last-error fields are cleared;
- rebuild after clear regenerates only the explicitly selected revision;
- a test-time model change is preceded by explicit clear; no profile/model
  version is persisted or inferred;
- interrupted build resumes;
- outside-revision closest vector never appears;
- global over-fetch/filter is absent;
- conflicting artifact fails.

Benchmark exact search over the real approximately 12,402-message 700K
revision: ten warm top-20 message queries and ten chunk queries, p95 <= 2.0
seconds each on the execution machine. Record hardware/sqlite-vec version and
all timings. If the real implementation cannot meet the bound after SQL/index
profiling, stop and report the measured blocker; do not reintroduce duplicate
partitions as a hidden fallback.

Gate: sparse artifact tests, scale tests, and benchmark pass.

## EWC15-310 - Exact evidence-block persistence

Rewrite evidence models/repository/rendering for exact message-ID ranges,
materialized block messages, origin revision, associations, edit validation,
canonical deletion protection, and content-hash integrity. Remove persisted
slot assumptions; derive UI positions from exact lists.

Adapt printable artifacts and every block consumer. Tests cover insertion
before/inside/after a block, revision addition/removal, highlight/core/boundary
validation, explicit detachment on edit, delete restriction, source-hash
change detection, explicit cross-corpus association, rejected destructive
reimport, and print/render order.

Gate: evidence/artifact tests pass; no persisted-slot production query remains.

## EWC15-400 - Explicit revision across local workflows

Route FTS, spellfix, embedding, transcript, conversational payloads, hints,
citations, and visible history through `validate_ready_scope`. Use
`remote_scope_id`. Remove dataset-only/implicit/current lookups below the UI
selection boundary.

Use cross-revision/corpus sentinels and concurrent work to prove isolation and
captured-scope stability.

Gate: every local operation is exact-revision scoped; server remains EVW-blind.

## EWC15-500 - Python revision selector

Implement file 03 selector/Refresh/CLI behavior only. No corpus editor. Adapt
workers/progress, explicit clear control, and integration tests to one EVW with
100K/700K revisions.

Gate: no auto-selection, revision gating, A-B-A switching, worker capture,
whole/windowed behavior, sparse reuse, explicit clear visibility/preservation,
and zero selection writes all pass.

## EWC15-600 - Flutter v15 multi-revision viewer

Implement file 03 read-only structure, exact six-file map, revision/evidence
display and paging, `--corpus-revision-id`, v15 probe, and no-write checks.

Gate: analyze, tests, Windows release build, and real v15 probe pass.

## EWC15-700 - One manual fixture and real end-to-end matrix

Migrate `.tmp/sfv1-fixture-100k.evw`, create/publish 700K revision 2, produce
`.tmp/sfv1-fixture-multicorpus-v15.evw`, validate token bands, then build 100K
and 700K embeddings in that order after one explicit cache clear.

With one fake-provider subprocess and public workflows prove:

- both current revisions ready simultaneously;
- all local/remote modes use exact selected revision;
- 100K chooses whole;
- 700K chooses windowed ledger;
- second embedding build reports reuse and sends only misses;
- switch back requires no rebuild;
- correct conversation/evidence provenance;
- concurrent revision isolation;
- no user-content server persistence/logging.

Gate: automated subprocess E2E and real fixture validation pass.

## EWC15-800 - Documentation, packaging, and architecture scans

Update current README/manual instructions to one v15 EVW. Replace verifier and
CLI references. Mark older active/two-EVW instructions superseded without
rewriting historical logs.

Scan runtime/package/Dart/current docs for forbidden structures and method
names. Inspect built wheel/sdist and Flutter release assets.

Gate: scans/package tests pass with only explicit migration/negative-spec hits.

## EWC15-900 - Full verification and closeout

Run file 06 completely. Inspect final diff for unrelated edits, secrets,
temporary artifacts, compatibility paths, swallowed errors, fake tests, and
leaked processes.

Create `closeout_report.md` with ticket status, commands/results, schema and
migration inventory, sparse hit/miss evidence, benchmark, evidence migration/
compatibility evidence, one-EVW whole/windowed behavior, Flutter no-write
proof, WAL/integrity, deletions, and exact lean human-visible test instructions.

Gate: no required work remains.

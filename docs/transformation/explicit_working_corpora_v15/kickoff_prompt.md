# Explicit Working Corpora V15 Executor Kickoff

Repository:

`C:\Users\artwh\OneDrive\Documents\legal2`

Implement the complete authoritative packet:

`C:\Users\artwh\OneDrive\Documents\legal2\docs\transformation\explicit_working_corpora_v15\README.md`

Before editing:

1. Read repository `AGENTS.md`.
2. Read every packet document in README order.
3. Inspect and record the dirty-worktree/baseline required by EWC15-000.
4. Do not execute or preserve the earlier version of this packet. This revised
   packet includes immutable corpus revisions, sparse shared embeddings, and
   durable evidence associations.

Execute EWC15-000 through EWC15-900 in dependency order. Complete each ticket's
real implementation, targeted tests, and evidence before dependent work.
Maintain:

`C:\Users\artwh\OneDrive\Documents\legal2\docs\transformation\explicit_working_corpora_v15\execution_log.md`

Non-negotiable architecture:

- EVW runtime is v15 only.
- One canonical dataset feeds durable named working corpora.
- Each corpus has immutable revisions and at most one published current
  revision.
- There is no global active/selected corpus and no automatic UI selection.
- Editing creates a draft revision; ready membership is never rewritten.
- Every operation captures an explicit revision scope.
- Embedding storage is a sparse content-addressed local cache. Never precompute
  the full corpus.
- Overlapping/new revisions reuse matching message/chunk artifacts and send
  only cache misses to the existing server embedding endpoint.
- The existing embeddings endpoint contract stays unchanged. Do not add a
  profile handshake, expected-profile field, capabilities route, or fourth
  route.
- The production embedding model is fixed. Persist no provider/model/profile/
  revision/fingerprint identity in the EVW.
- Testing gets one explicit `Clear local embeddings` action. It atomically
  removes vectors/cache geometry and marks all embedding coverage missing while
  preserving canonical/user data, corpora/revisions/membership, lexical
  indexes, deterministic chunks, evidence, conversations, and settings. It is
  confirmed, disabled during workers, counted, noisy on failure, and never
  automatic.
- Vector search ranks only the selected revision's membership through exact
  scalar-distance SQL; never global-KNN then filter and never duplicate vectors
  solely for corpus partitions.
- Evidence blocks are canonical artifacts with exact ordered message IDs,
  durable ID boundaries, origin revision/scope, and explicit compatible
  revision associations.
- Removed block messages create explicit publication conflicts. Never silently
  shrink, repair, delete, or detach evidence.
- Legacy positional evidence migration requires an explicit scope map; never
  guess.
- Python gains only the lean revision selector needed to test current flows.
- Flutter remains read-only and views multiple corpora/revisions/evidence in
  one EVW.
- The FastAPI server remains stateless and EVW-blind; this cache work makes no
  production server behavior change.
- One v15 EVW proves both approximately 100K whole-corpus and approximately
  700K windowed behavior plus embedding reuse.

This is a clean break. Delete old active, mutable membership, duplicate vector
partition, singleton vector metadata, positional evidence persistence, v14
runtime, and compatibility APIs. Do not hide them behind aliases.

Run all dependency installation, builds, migration, fixture preparation,
benchmarking, and automated verification yourself. Do not assign setup or
automated tests to the user. Preserve unrelated changes. Never expose secrets.
Do not commit, push, or deploy unless separately instructed.

Continue until every local gate in `06_acceptance_gates.md` passes. Run live
provider validation only if approved configured credentials are available. If
not, complete every non-live gate and record that single external omission.

At completion create:

`C:\Users\artwh\OneDrive\Documents\legal2\docs\transformation\explicit_working_corpora_v15\closeout_report.md`

Include ticket dispositions, commands/results, schema/migration inventory,
revision publication evidence, sparse cache hit/miss workloads, exact-vector
benchmark, evidence compatibility/migration proof, one-EVW whole/windowed
results, Flutter no-write proof, WAL/integrity, deletions, and lean human-visible
testing instructions.

Begin with EWC15-000.

# Verification Audit — 2026-07-18

The binding remediation plan is now
`docs/transformation/phase_1_4_closeout/README.md`. It deliberately replaces the
experimental v13/runtime-compatibility result with EVW v14, API v2, mandatory
working-corpus scope, remote-only model/embedding execution, one writer, and a
real read-only Flutter viewer.

The completion claim in `execution_log.md` is not a valid Phase 1–4 acceptance
result. Post-execution review found and corrected concrete defects in Flutter
probe awaiting/exit behavior, FTS phrase coverage, client/server embedding
recursion, package contents, plaintext client credentials, v12 migration
dispatch, compact-migration over-limit behavior, WAL checkpoint handling,
read-only search connections, default date scoping, working-corpus
materialization, schema cardinality constraints, and hidden client-side model
configuration gates. The server now advertises its selected model, context
limit, and output limit; the production client uses those values for local
window planning.

## Binding work still incomplete

- `WorkingCorpusScope` is not yet the required argument or resolved scope for
  every FTS, vector, transcript, window-planning, and conversational path.
- FTS rows and queries are not yet partitioned by `working_corpus_id`.
- sqlite-vec rows, metadata, index jobs, and KNN queries are not yet fully
  partitioned by `<model_name>\x1f<working_corpus_id>`.
- `WorkspaceConnection` is not yet the sole writer used by UI/background jobs;
  several workers still open independent write connections.
- Fresh imports do not yet create and activate a default working corpus through
  one obvious end-to-end path, and there is no working-corpus builder UI for
  narrowing a failed over-limit migrated corpus.
- There is no exclusive workspace lock preventing two application processes
  from opening the same EVW for writing.
- The Python client retains explicit legacy in-process model branches for unit
  tests. Production resolution is server-only, but the source boundary should
  still be completed by moving or removing those branches.
- The Flutter release probe passes against a real v13 EVW, but no real legacy
  v12 production copy was available in this workspace for the required
  copy-based compatibility run.

## Verified gates after correction

- 487 non-UI Python tests passed (11 deselected).
- 27 virtual-transcript tests passed.
- 71 transformation-targeted tests passed.
- All 40 UI smoke tests passed as one batch after background-session isolation
  was corrected.
- Flutter tests and Windows release build passed.
- Release probe passed 27/27 and 28/28 against a real v13 EVW.
- A live fake-model server/client remote-embedding round trip passed.
- The built Python wheel contains the `server` package and frozen prompt set;
  the packaged prompt JSON is identical to the specification copy.

The known pre-existing chunk-calibration test remains red: expected 20 chunks,
received 1. A monolithic all-tests run timed out without a result, although the
segmented suites above pass. Neither issue should be hidden or counted as a
green full-regression gate.

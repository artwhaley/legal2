# Clients, Fixtures, and Migration Contract

## Python integration harness

The temporary PySide client gains one lean corpus/revision selector and explicit
Refresh. Do not add corpus editing/creation/deletion UI.

Selector rows show:

```text
corpus name | revision number | current/older | revision status
message count | token count | lexical generation | embedding coverage
```

Behavior:

- Initial state is `Select a working-corpus revision`; no automatic selection.
- List every corpus and revision.
- Selecting a ready, current-canonical revision captures its immutable scope.
- Stale/failed/building/draft rows remain visible with exact reason but cannot
  run searches.
- Refresh clears selection if the exact scope no longer validates.
- Search/build buttons remain disabled without a valid explicit scope.
- Embedding/conversation workers capture the selected scope before starting.
- Selector/Refresh and `Clear local embeddings` are disabled while any local
  search, embedding, or conversation worker runs.
- Selection writes nothing to the EVW.
- Switching revision A1 -> B1 -> A1 does not rebuild or mutate either.
- `Clear local embeddings` requires an explicit confirmation, invokes the one
  service operation from file 02, and reports exact artifact/index counts. It
  does not require a selected revision because it deliberately clears the
  entire EVW-local cache.
- After a clear, embedding search/build readiness is visibly missing for every
  revision until each selected revision is explicitly rebuilt. Lexical search
  remains ready.

Add required optional argument:

```text
--corpus-revision-id INTEGER
```

When supplied, it explicitly preselects that ready revision or fails startup
visibly. Remove the previous proposed `--corpus-id`; revision identity is the
search boundary.

## Flutter read-only viewer

Flutter remains read-only and server-blind. It displays:

- canonical Full Corpus;
- all named working corpora;
- current and historical revisions;
- frozen selection definition;
- revision status, revision number, canonical revision, counts, hash, lexical
  generation, embedding coverage/cache dimensions, and last error;
- selected revision membership/transcript through paged SQL;
- evidence blocks associated with the selected revision, including origin and
  exact range count.

It does not auto-select a corpus/revision or write last selection.

Invocation:

```text
evw_client.exe --evw PATH
evw_client.exe --evw PATH --corpus-revision-id ID
evw_client.exe --probe --evw PATH --corpus-revision-id ID
```

Unknown/non-viewable IDs fail visibly. Stale/failed revision metadata remains
viewable and clearly non-searchable.

Use exactly:

```text
main.dart
src/evw_database.dart
src/evw_models.dart
src/workspace_view.dart
src/compatibility_probe.dart
src/native_extensions.dart
```

No extra state framework, ORM, polling, server call, corpus editor, fake screen,
or one-file-per-control structure.

## V15 explicit compact-copy migration

Runtime never migrates. Command:

```powershell
python -m message_evidence_workstation.tools.migrate_evw `
  SOURCE.evw --destination TARGET.evw
```

It accepts known v12, experimental v13, and v14; writes v15. If v12/v13 has no
working-corpus tables, create one named `Full Corpus` with revision 1 using the
`all` definition. Build/publish it only when it is nonempty and within 768,000
tokens; otherwise retain the failed revision with no current pointer. Never
embed it during migration.

### Corpus conversion

For each old `working_corpus` row:

1. Preserve its ID as a named `working_corpus` where possible.
2. Create revision 1 containing its old definition, membership, status,
   canonical revision, counts, hash, and converted lexical generation.
3. Ignore old `is_active` for all selection semantics.
4. If old status is ready or stale and membership is structurally valid, set
   that named corpus's `current_revision_id` to revision 1.
5. Draft/building/failed old rows have no published current revision.
6. Preserve stale as stale; do not infer whether old activation caused it.

Reconstruct ready/stale FTS and spellfix from canonical text and exact copied
membership. Fail on inconsistent ready metadata.

### Embedding conversion

Convert old validated corpus-partitioned vectors into sparse artifacts:

- compute canonical message/chunk input hashes;
- require one consistent dimensions/normalization geometry across every
  retained vector;
- write that geometry to `embedding_cache_state`;
- collapse duplicate rows by exact `input_hash`;
- require duplicate source vectors for one artifact key to be byte-identical
  after validated float32 serialization;
- fail with source corpus/generation/ID when they conflict;
- recompute per-revision coverage/component status.

Old provider/model/profile/revision/fingerprint values are deliberately
ignored and are not copied. The fixed-model invariant treats retained vectors
as one cache; incompatible geometry or conflicting vectors fails visibly.

Support only this explicit discard:

```text
--discard-derived-embeddings
```

With the flag, omit old vector artifacts and cache geometry, preserve
deterministic chunk text, mark message/chunk coverage missing, and report every
discarded partition. Never discard implicitly.

### Legacy positional evidence

V14 evidence blocks store positional slots but not the ordered scope used to
interpret them. Migration must not guess.

If the source contains any evidence block, require:

```text
--legacy-evidence-scope-map PATH.json
```

JSON shape:

```json
{
  "123": {"kind": "working_corpus", "working_corpus_id": 2},
  "124": {"kind": "canonical_thread"}
}
```

When the map is absent, migration writes
`<destination>.legacy-evidence-scope-report.json` and then fails before creating
the destination. The content-free report lists each block ID, thread, slot
tuple, core/highlight IDs, and candidate old corpora whose ordered thread
membership can satisfy all constraints. It never writes message bodies.

For `working_corpus`, resolve old slots against that corpus's ordered
same-thread membership. For `canonical_thread`, resolve against canonical
thread order and set `origin_kind=legacy_dataset`.

Conversion:

- start slots point to the indexed start message;
- end slots are exclusive, so boundary message is `end_slot - 1`;
- context and relevant ranges must be nonempty and contain the core in the
  relevant range;
- materialize every context-range ID and section;
- validate core/highlights inside the range;
- record origin revision when mapped to a corpus;
- associate with every converted revision whose complete membership contains
  the block range, starting with the mapped origin.

Missing/invalid/ambiguous mapping fails migration without changing source or
destination. No default canonical-thread interpretation exists.

The current manual v14 fixtures contain zero evidence blocks, so they require
no scope map.

### File safety

- Recover/checkpoint through SQLite; never delete WAL manually.
- Read source without editing the only copy.
- Write a temporary target in destination directory.
- Preserve canonical/user data, working definitions/membership, visible
  conversations, evidence/artifacts, settings allowlist, IDs, and timestamps.
- Run quick/foreign-key/structural/revision/evidence/embedding validation.
- Replace destination only after all validation passes.
- Failed migration leaves source/destination unchanged.

## One manual multi-revision fixture

Input:

```text
.tmp/sfv1-fixture-100k.evw
```

Output:

```text
.tmp/sfv1-fixture-multicorpus-v15.evw
```

The v14 input already contains legal date definitions:

- `Recent ~700K Tokens`, approximately 698,786 tokens, stale only because of
  the old activation lifecycle;
- `Recent ~100K Tokens (Whole-Corpus Test)`, approximately 99,980 tokens.

Migrate it. For the 700K named corpus, create revision 2 from revision 1, build
the unchanged definition against current canonical data, and publish revision
2. Keep revision 1 as historical stale provenance. The 100K corpus's valid
revision 1 remains current.

Required bands:

```text
windowed current revision: 650,000 through 720,000
whole current revision:     80,000 through 120,000
```

Both current revisions are ready simultaneously in one EVW.

After migration, invoke `Clear local embeddings` once so the manual cache test
starts from a known empty state. Build embeddings for 100K first, then 700K.
The second workload must reuse the overlap and send only hashes not already
present. Record cleared/requested/reused/miss counts without message text.

## Human-visible walkthrough

Using the one v15 EVW and one server:

1. Use `Clear local embeddings`; verify explicit confirmation, nonzero cleared
   count when applicable, and missing embedding coverage for both revisions.
2. Select the 100K revision in Python and run FTS, keyword, embedding
   build/search, and conversational analysis; verify whole-corpus strategy.
3. Select the 700K revision and repeat; verify windowed-ledger strategy and
   sparse embedding reuse.
4. Switch back to 100K and search without rebuild.
5. Open the same EVW in Flutter and inspect both current revisions plus the
   historical stale 700K revision.
6. Verify selection caused no corpus/revision/status write or WAL residue.

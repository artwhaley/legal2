# Acceptance Gates

## Schema and migration

- Fresh runtime file is exactly v15.
- Runtime rejects v12/v13/v14 byte-for-byte unchanged.
- No global corpus active/selected state exists.
- Corpus current pointer references only its own revision.
- Ready revision definition/membership cannot mutate.
- V14 corpus rows become named corpora plus revision 1; old active flag is
  irrelevant.
- Canonical/user data, IDs, visible history, evidence, and artifacts preserve.
- FTS/spellfix reconstruct exactly.
- Valid old vectors collapse into sparse artifacts.
- Old embedding profile/model identity is not copied into v15.
- Retained vector geometry must be internally consistent.
- Conflicting duplicate vectors fail.
- Embedding discard occurs only with explicit flag.
- Legacy evidence requires and obeys exact scope map.
- Missing/ambiguous legacy evidence scope fails without output replacement.
- Reimport against an existing canonical dataset fails before mutation.
- Quick check, foreign keys, structural validator, and allow/deny lists pass.

## Revision lifecycle

- Multiple corpus current revisions are ready simultaneously.
- A1 remains immutable while A2 is drafted/built/published.
- Failed A2 leaves A1 current.
- Publishing a draft whose base is no longer current fails without mutation.
- A2 publication does not affect corpus B.
- Older ready revision remains explicitly searchable until canonical revision
  changes.
- Empty revision builds but network-required actions fail before HTTP.
- Exactly 768,000 tokens builds; 768,001 fails without pointer change.
- Canonical revision/hash mismatch blocks search/persistence.
- No global/implicit revision fallback exists.

## Sparse embeddings

Use canonical messages:

```text
A_ONLY
B_ONLY
A_B_OVERLAP
OUTSIDE_ALL
```

Prove:

- cache starts empty;
- the client sends no content-free handshake and no expected-profile field;
- no provider/model/profile/revision/fingerprint identity is stored in the EVW;
- no artifact input-kind or input-format version is stored or used as a key;
- building A creates only A/overlap artifacts;
- building B reuses overlap and sends only B-only misses;
- outside-all remains unembedded;
- a new A revision with ten additions sends only uncached additions;
- an addition already embedded by B causes no provider call;
- unchanged chunk hashes reuse; changed chunks miss;
- identical exact message/chunk text shares one artifact;
- exact text change misses;
- resume sends only unresolved hashes;
- component ready requires complete exact coverage;
- selected-revision KNN never returns outside members even when their cached
  vector is globally closest;
- query vector is not persisted;
- no corpus-duplicate vector rows exist.
- explicit clear deletes all artifacts and cache geometry in one transaction;
- explicit clear marks every revision's message/chunk coverage missing;
- explicit clear clears only component-specific embedding errors;
- explicit clear preserves canonical/user data, revisions, membership,
  FTS/spellfix, deterministic chunks, evidence, conversations, and settings;
- clear is disabled during local workers, requires confirmation, reports exact
  counts, and never runs automatically;
- rebuilding after clear embeds only the explicitly selected revision;
- Python/native probe both report pinned sqlite-vec v0.1.9 and verified native
  checksum.

The real 700K benchmark in ticket 300 must meet p95 <= 2.0 seconds for both ten
warm message and ten warm chunk top-20 queries.

## Evidence durability

- New block stores exact ordered message IDs and ID boundaries.
- Origin revision/scope is recorded.
- Every block message is a member of each associated revision.
- Adding messages preserves compatible association.
- Removing an unrelated message preserves association.
- Removing any stored block message produces explicit publication conflict.
- Publication cannot proceed until incompatible IDs are exactly acknowledged
  as excluded.
- Old revision/block association remains unchanged.
- Inserting canonical messages does not silently change an existing block's
  exact message range.
- Referenced message hard delete fails with reference IDs.
- Changed message hash makes block integrity visibly invalid.
- Block edit requires explicit incompatible-association detachments.
- Printable artifact/rendering uses exact block-message order.
- No v15 evidence persistence depends on slots.

## Search/client/server isolation

For FTS, spellfix, keyword lookup, vectors, transcript payload, conversation,
hints, citations, and history:

- A never returns/sends B-only or outside-all data.
- B never returns/sends A-only or outside-all data.
- A/B concurrent calls remain isolated.
- UI changes cannot redirect a captured worker.
- Python/Flutter initially select no revision.
- Selection causes no database write.
- `--corpus-revision-id` is explicit and validated.
- Server routes remain exactly the existing three.
- Server imports/opens/persists no EVW or corpus state.
- Existing `/v1/embeddings` request contract remains unchanged.
- No capabilities/profile/cache-management route exists.

## Required commands

Record exact commands and results:

```powershell
python -m compileall -q message_evidence_workstation server tests
python scripts\verify_package_boundaries.py
python -m pytest -q -m "not scale" --timeout=90
python -m pytest -q -m scale --timeout=240
python -m build
git diff --check
```

```powershell
python scripts\verify_evw_v15.py `
  .tmp\sfv1-fixture-multicorpus-v15.evw
```

```powershell
cd flutter_client
flutter pub get
flutter analyze
flutter test
flutter build windows --release
build\windows\x64\runner\Release\evw_client.exe `
  --probe `
  --evw ..\.tmp\sfv1-fixture-multicorpus-v15.evw
```

No known red, timeout, leaked subprocess, skipped in-scope test, xfail, or fake
success is accepted.

## Required scans

At minimum scan runtime/current docs for:

```text
is_active
idx_working_corpus_active
get_active(
activate(
active_scope(
require_active
working_corpus_message
working_corpus_index
vector_store_metadata
embedding_profile_id
artifact_fingerprint
model_revision
message_embedding_vec
chunk_embedding_vec
context_start_slot
relevant_start_slot
relevant_end_slot
context_end_slot
--corpus-id
Active Search Corpus
active working corpus
```

Allowed hits:

- explicit old-schema migration readers;
- negative assertions;
- existing server wire contracts and server implementation;
- transient UI slot helper calculations;
- this packet explaining deletions.

No v15 runtime persistence/query or current user instruction may require the
removed structures.

Also inspect every `WorkingCorpusScope`, revision resolution, vector-distance,
and evidence-block creation call site manually.

## Final human-visible test handoff

The executor performs dependencies, builds, migration, fixture creation,
server setup from existing approved configuration, and automated tests. The
user receives only:

1. exact server start command;
2. exact Python start command against the one v15 EVW;
3. exact clear/rebuild actions and visible queries for 100K then 700K then
   100K;
4. exact Flutter executable/path and revision selections;
5. expected strategy, reuse, counts, and visible success/failure labels.

Do not assign setup or automated verification to the user.

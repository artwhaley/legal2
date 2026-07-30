# Explicit Working Corpora V15 Patch

This packet establishes the durable local-data model required before the
Flutter client becomes writable:

```text
one canonical dataset
  -> durable named working corpora
     -> immutable working-corpus revisions
        -> revision membership and lexical indexes

canonical text
  -> sparse reusable embedding artifacts

canonical evidence blocks
  <-> compatible working-corpus revisions
```

It supersedes every conflicting EVW-version, active-corpus, mutable-membership,
corpus-local-vector, and positional-evidence requirement in:

- `docs/transformation/phase_1_4_closeout`
- `docs/transformation/server_first_v1`
- the earlier version of this packet

Those packets remain historical evidence for unrelated completed work. This
packet is authoritative for EVW v15, corpus/revision selection, embedding
storage, evidence-block durability, migration, Python-harness behavior,
Flutter display, fixtures, and current acceptance gates.

Read in order:

1. `00_mission_and_invariants.md`
2. `01_schema_embedding_and_evidence.md`
3. `02_repository_revision_lifecycle.md`
4. `03_clients_fixtures_and_migration.md`
5. `04_file_map.md`
6. `05_ticket_stack.md`
7. `06_acceptance_gates.md`
8. `07_executor_protocol.md`

Execution starts with `kickoff_prompt.md`.

## Binding end state

- Runtime EVW schema is v15 only.
- One EVW contains one canonical dataset and any number of named working
  corpora.
- There is no global active/selected/current corpus.
- Each named corpus has immutable revisions and at most one published current
  revision.
- Editing a corpus creates a draft revision; it never rewrites a ready
  revision.
- Every operation captures an explicit immutable revision scope.
- Message/chunk embeddings are sparse, local, content-addressed artifacts.
  Only text requested by a working-corpus embedding build is embedded.
- Overlapping corpora and later revisions reuse matching artifacts and call
  the server only for missing content hashes.
- Vector search computes exact distances only across the selected revision's
  membership; cached vectors outside that revision cannot appear.
- Evidence blocks are canonical user artifacts with exact ordered message IDs,
  durable message-ID boundaries, origin provenance, and explicit compatible
  revision associations.
- Removing a message from a new revision never mutates/deletes an existing
  block. Publishing stops for an explicit evidence compatibility decision.
- Referenced canonical messages cannot be hard-deleted silently.
- Python gets only the corpus/revision selector needed for integration testing.
- Flutter remains read-only and inspects multiple corpora/revisions in one EVW.
- The stateless FastAPI server remains EVW-blind and keeps the existing three
  product endpoints and existing embeddings request contract.
- The production embedding model is fixed. The EVW stores no model/profile
  version; testing gets one explicit local-cache clear action before model
  changes.
- One v15 fixture contains both the approximately 100K whole-corpus revision
  and approximately 700K windowed revision.

## Clean-break rule

Delete, do not retain:

- `working_corpus.is_active` and its index;
- activation APIs and implicit active-scope lookup;
- mutable ready-corpus membership;
- corpus/generation-partitioned duplicate message-vector storage;
- the old `vector_store_metadata` table and corpus-partitioned vector model;
- embedding model/profile/version identity in the EVW;
- positional evidence-block slots in v15;
- runtime v14 compatibility.

Do not add aliases, fallback lookups, hidden auto-selection, automatic
embedding of the full corpus, automatic evidence truncation, or schema-shaped
compatibility residue.

# Evidence, persistence, and print contracts

## Exact range evidence creation

Add one database operation for conversational ranges. Its input is revision
ID, start ID, end ID, title, summary, creator, and optional range ID.

Within one immediate transaction:

1. require the selected ready scope;
2. load both endpoints from revision membership;
3. require same source thread and start ordinal <= end ordinal;
4. load every inclusive same-thread revision member;
5. load at most three same-thread members before start and after end;
6. choose lower median relevant member as core;
7. write one `evidence_block`;
8. write exact `evidence_block_message` rows and sections;
9. highlight core only;
10. associate it with the selected revision;
11. touch workspace state;
12. re-read and return the complete block.

Use existing content-hash generation and `_write` transaction machinery.
Factor shared private helpers rather than duplicating insertion SQL. Existing
hit-centered creation must continue to behave exactly as before.

`created_by` is `fts_search`, `embedding_search`, or
`conversational_search` as applicable. Extend the hit creation method to
accept this explicit creator; transcript-manual creation remains
`transcript_editor`.

## Shared evidence behavior

Search, Conversation, and Transcript instantiate separate
`TranscriptEvidenceEditor` widgets with the same controller. A save from any
page:

- selects the new block;
- causes all transcript renderers to repaint from shared state;
- advances evidence data version;
- scrolls the initiating page's transcript to the core;
- makes the print page reload when next active.

Boundary preview stays in memory until drag end. Persistence failure reloads
the authoritative block and shows the original error.

Offstage transcript renderers must not change active evidence. Add widget tests
with two mounted transcript views proving the active page alone controls
center-line handoff.

## Print repository

Add typed Dart models and `EvwDatabase` methods for only the V1 print actions:

- list groups;
- list artifacts;
- ensure default group;
- create artifact from evidence;
- update metadata;
- append evidence;
- load artifact with ordered exact evidence/messages;
- move one join row up/down by transactionally rewriting contiguous sort
  order;
- remove one join row.

Validate dataset ownership for group, artifact, and evidence association.
Reject duplicate attachment of the same evidence block to one artifact rather
than creating indistinguishable duplicates. Existing historical duplicates,
if any, remain displayable and removable.

Every write uses `_write`, touches workspace state, verifies affected row
counts, and returns refreshed authoritative data. Do not port Python logger
calls or its internal commits.

## EVW validation

Extend Flutter open-time shape validation for every table/column now used:

- `message_fts`;
- `embedding_artifact`;
- `embedding_cache_state`;
- `conversation`;
- `conversation_turn`;
- `conversation_citation`;
- `printable_artifact_group`;
- `printable_artifact`;
- `printable_artifact_evidence_block`;
- message columns used for deterministic ordering and display;
- revision-index columns used for ready/FTS/embedding checks.

Do not require spellfix for this client path. Do not create or migrate missing
tables on open. A malformed v15 EVW fails noisily before the main pages become
available.

## Conversation persistence

Use the existing schema. Persist one conversation and one turn per completed
question in V1, matching current Python behavior. `presented_answer` is the
exact human-visible rendering, including warnings/status. Insert citations
only for verified message IDs. Do not invent a private JSON envelope or schema
extension in this packet.

Current-session cards retain typed structured results and full interactive
ranges in memory. Loading historical conversations and reconstructing saved
ranges are explicitly deferred because the existing citation schema does not
persist complete range identity safely.


"""Authoritative EVW v15 schema.

The file contains canonical transcript data, durable working-corpus revisions,
local lexical/vector indexes, evidence artifacts, visible chat history, and
user settings. Provider payloads, prompts, model-run traces, and diagnostics
are deliberately not persisted here.
"""

CREATE_TABLES_SQL = r"""
CREATE TABLE schema_version (version INTEGER NOT NULL CHECK (version = 15));

CREATE TABLE dataset (
    dataset_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 15),
    notes TEXT NOT NULL DEFAULT '',
    content_revision INTEGER NOT NULL DEFAULT 1 CHECK (content_revision >= 1),
    import_validity TEXT NOT NULL DEFAULT 'ready',
    import_error TEXT NOT NULL DEFAULT '',
    normalized_format_version INTEGER
);
CREATE UNIQUE INDEX idx_dataset_singleton ON dataset((1));

CREATE TABLE source_thread (
    source_thread_id TEXT NOT NULL,
    dataset_id INTEGER NOT NULL,
    source_platform TEXT NOT NULL,
    platform_thread_id TEXT NOT NULL,
    display_title TEXT NOT NULL,
    participant_summary TEXT NOT NULL DEFAULT '',
    start_ts TEXT NOT NULL,
    end_ts TEXT NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (dataset_id, source_thread_id),
    UNIQUE (source_thread_id),
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id) ON DELETE CASCADE
);

CREATE TABLE message (
    message_id TEXT NOT NULL,
    dataset_id INTEGER NOT NULL,
    source_thread_id TEXT NOT NULL,
    source_platform TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    sender_id TEXT NOT NULL,
    sender_display TEXT NOT NULL,
    body TEXT NOT NULL,
    body_normalized TEXT NOT NULL,
    embedding_input_hash TEXT NOT NULL CHECK(length(embedding_input_hash) = 64),
    has_attachment INTEGER NOT NULL DEFAULT 0,
    attachment_summary TEXT NOT NULL DEFAULT '',
    sort_index INTEGER NOT NULL,
    source_metadata_json TEXT NOT NULL DEFAULT '{}',
    thread_ordinal INTEGER NOT NULL DEFAULT 0,
    token_count INTEGER NOT NULL DEFAULT 0 CHECK(token_count >= 0),
    PRIMARY KEY (dataset_id, message_id),
    UNIQUE (message_id),
    FOREIGN KEY (dataset_id, source_thread_id)
        REFERENCES source_thread(dataset_id, source_thread_id) ON DELETE RESTRICT
);
CREATE INDEX idx_message_thread_order ON message(dataset_id, source_thread_id, thread_ordinal, timestamp, sort_index, message_id);
CREATE INDEX idx_message_timestamp ON message(dataset_id, timestamp, message_id);

CREATE TABLE category (
    category_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '',
    is_collapsed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id) ON DELETE CASCADE
);

CREATE TABLE workspace_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE workspace_setting (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE workspace_event (
    workspace_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    dataset_id INTEGER,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id) ON DELETE SET NULL
);

CREATE TABLE working_corpus (
    working_corpus_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL REFERENCES dataset(dataset_id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    current_revision_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (working_corpus_id, current_revision_id),
    FOREIGN KEY (working_corpus_id, current_revision_id)
        REFERENCES working_corpus_revision(working_corpus_id, working_corpus_revision_id)
);
CREATE INDEX idx_working_corpus_dataset ON working_corpus(dataset_id, created_at, working_corpus_id);

CREATE TABLE working_corpus_revision (
    working_corpus_revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    working_corpus_id INTEGER NOT NULL REFERENCES working_corpus(working_corpus_id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL CHECK(revision_number >= 1),
    base_revision_id INTEGER,
    selection_mode TEXT NOT NULL CHECK(selection_mode IN ('all', 'selected')),
    start_date TEXT,
    end_date TEXT,
    token_limit INTEGER NOT NULL CHECK(token_limit = 768000),
    estimated_tokens INTEGER NOT NULL DEFAULT 0 CHECK(estimated_tokens >= 0),
    message_count INTEGER NOT NULL DEFAULT 0 CHECK(message_count >= 0),
    tokenizer_id TEXT NOT NULL,
    scope_hash TEXT NOT NULL DEFAULT '',
    dataset_content_revision INTEGER NOT NULL CHECK(dataset_content_revision >= 1),
    status TEXT NOT NULL CHECK(status IN ('draft', 'building', 'ready', 'stale', 'failed')),
    last_error TEXT,
    created_at TEXT NOT NULL,
    built_at TEXT,
    UNIQUE (working_corpus_id, revision_number),
    UNIQUE (working_corpus_id, working_corpus_revision_id),
    FOREIGN KEY (working_corpus_id, base_revision_id)
        REFERENCES working_corpus_revision(working_corpus_id, working_corpus_revision_id)
);
CREATE INDEX idx_working_corpus_revision_list ON working_corpus_revision(working_corpus_id, revision_number DESC);
CREATE INDEX idx_working_corpus_revision_status ON working_corpus_revision(status, dataset_content_revision);
CREATE TABLE working_corpus_revision_source (
    working_corpus_revision_id INTEGER NOT NULL REFERENCES working_corpus_revision(working_corpus_revision_id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    PRIMARY KEY (working_corpus_revision_id, source_name)
);
CREATE TABLE working_corpus_revision_thread (
    working_corpus_revision_id INTEGER NOT NULL REFERENCES working_corpus_revision(working_corpus_revision_id) ON DELETE CASCADE,
    source_thread_id TEXT NOT NULL REFERENCES source_thread(source_thread_id) ON DELETE RESTRICT,
    PRIMARY KEY (working_corpus_revision_id, source_thread_id)
);

CREATE TABLE working_corpus_revision_message (
    working_corpus_revision_id INTEGER NOT NULL REFERENCES working_corpus_revision(working_corpus_revision_id) ON DELETE RESTRICT,
    message_id TEXT NOT NULL REFERENCES message(message_id) ON DELETE RESTRICT,
    source_thread_id TEXT NOT NULL REFERENCES source_thread(source_thread_id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    token_count INTEGER NOT NULL CHECK(token_count >= 0),
    embedding_input_hash TEXT NOT NULL CHECK(length(embedding_input_hash) = 64),
    PRIMARY KEY (working_corpus_revision_id, message_id),
    UNIQUE (working_corpus_revision_id, ordinal)
);
CREATE INDEX idx_revision_message_order ON working_corpus_revision_message(working_corpus_revision_id, source_thread_id, ordinal);

CREATE TABLE working_corpus_revision_index (
    working_corpus_revision_index_id INTEGER PRIMARY KEY AUTOINCREMENT,
    working_corpus_revision_id INTEGER NOT NULL REFERENCES working_corpus_revision(working_corpus_revision_id) ON DELETE CASCADE,
    index_generation INTEGER NOT NULL CHECK(index_generation >= 1),
    dataset_content_revision INTEGER NOT NULL CHECK(dataset_content_revision >= 1),
    status TEXT NOT NULL CHECK(status IN ('building', 'ready', 'stale', 'failed')),
    fts_status TEXT NOT NULL DEFAULT 'missing' CHECK(fts_status IN ('missing', 'building', 'ready', 'stale', 'failed')),
    spellfix_status TEXT NOT NULL DEFAULT 'missing' CHECK(spellfix_status IN ('missing', 'building', 'ready', 'stale', 'failed')),
    message_embedding_status TEXT NOT NULL DEFAULT 'missing' CHECK(message_embedding_status IN ('missing', 'building', 'ready', 'stale', 'failed')),
    chunk_embedding_status TEXT NOT NULL DEFAULT 'missing' CHECK(chunk_embedding_status IN ('missing', 'building', 'ready', 'stale', 'failed')),
    message_embedding_last_error TEXT,
    chunk_embedding_last_error TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (working_corpus_revision_id, index_generation)
);
CREATE INDEX idx_revision_index_latest ON working_corpus_revision_index(working_corpus_revision_id, index_generation DESC);

CREATE TABLE embedding_cache_state (
    cache_id INTEGER PRIMARY KEY CHECK(cache_id = 1),
    dimensions INTEGER NOT NULL CHECK(dimensions > 0),
    normalization TEXT NOT NULL CHECK(normalization IN ('unit_l2', 'none')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE embedding_artifact (
    input_hash TEXT PRIMARY KEY CHECK(length(input_hash) = 64 AND input_hash = lower(input_hash)),
    dimensions INTEGER NOT NULL CHECK(dimensions > 0),
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL,
    CHECK(length(vector) = dimensions * 4)
);
CREATE TRIGGER embedding_artifact_geometry_insert
BEFORE INSERT ON embedding_artifact
WHEN NOT EXISTS (SELECT 1 FROM embedding_cache_state)
  OR (SELECT dimensions FROM embedding_cache_state WHERE cache_id = 1) <> NEW.dimensions
BEGIN SELECT RAISE(ABORT, 'embedding cache geometry is not initialized or dimensions differ'); END;
CREATE TRIGGER embedding_artifact_geometry_update
BEFORE UPDATE OF dimensions ON embedding_artifact
WHEN NOT EXISTS (SELECT 1 FROM embedding_cache_state)
  OR (SELECT dimensions FROM embedding_cache_state WHERE cache_id = 1) <> NEW.dimensions
BEGIN SELECT RAISE(ABORT, 'embedding cache geometry dimensions differ'); END;

CREATE TABLE message_chunk (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    working_corpus_revision_id INTEGER NOT NULL REFERENCES working_corpus_revision(working_corpus_revision_id) ON DELETE RESTRICT,
    index_generation INTEGER NOT NULL,
    source_thread_id TEXT NOT NULL REFERENCES source_thread(source_thread_id) ON DELETE RESTRICT,
    start_message_id TEXT NOT NULL REFERENCES message(message_id) ON DELETE RESTRICT,
    end_message_id TEXT NOT NULL REFERENCES message(message_id) ON DELETE RESTRICT,
    message_count INTEGER NOT NULL CHECK(message_count > 0),
    char_count INTEGER NOT NULL CHECK(char_count >= 0),
    text_checksum TEXT NOT NULL CHECK(length(text_checksum) = 64),
    embedding_input_hash TEXT NOT NULL CHECK(length(embedding_input_hash) = 64),
    body_text TEXT NOT NULL,
    FOREIGN KEY (working_corpus_revision_id, index_generation)
        REFERENCES working_corpus_revision_index(working_corpus_revision_id, index_generation) ON DELETE RESTRICT
);
CREATE INDEX idx_message_chunk_scope ON message_chunk(working_corpus_revision_id, index_generation, source_thread_id);

CREATE TABLE evidence_block (
    evidence_block_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    source_thread_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    context_start_message_id TEXT NOT NULL,
    relevant_start_message_id TEXT NOT NULL,
    core_message_id TEXT NOT NULL,
    relevant_end_message_id TEXT NOT NULL,
    context_end_message_id TEXT NOT NULL,
    origin_kind TEXT NOT NULL CHECK(origin_kind IN ('working_corpus_revision', 'legacy_dataset')),
    origin_working_corpus_revision_id INTEGER REFERENCES working_corpus_revision(working_corpus_revision_id) ON DELETE RESTRICT,
    origin_scope_hash TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id) ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES category(category_id) ON DELETE RESTRICT,
    FOREIGN KEY (source_thread_id) REFERENCES source_thread(source_thread_id) ON DELETE RESTRICT,
    FOREIGN KEY (context_start_message_id) REFERENCES message(message_id) ON DELETE RESTRICT,
    FOREIGN KEY (relevant_start_message_id) REFERENCES message(message_id) ON DELETE RESTRICT,
    FOREIGN KEY (core_message_id) REFERENCES message(message_id) ON DELETE RESTRICT,
    FOREIGN KEY (relevant_end_message_id) REFERENCES message(message_id) ON DELETE RESTRICT,
    FOREIGN KEY (context_end_message_id) REFERENCES message(message_id) ON DELETE RESTRICT
);
CREATE TABLE evidence_block_message (
    evidence_block_id INTEGER NOT NULL REFERENCES evidence_block(evidence_block_id) ON DELETE CASCADE,
    message_id TEXT NOT NULL REFERENCES message(message_id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    section TEXT NOT NULL CHECK(section IN ('leading_context', 'relevant', 'trailing_context')),
    message_content_hash TEXT NOT NULL CHECK(length(message_content_hash) = 64),
    PRIMARY KEY (evidence_block_id, message_id),
    UNIQUE (evidence_block_id, ordinal)
);
CREATE TABLE evidence_block_highlight (
    evidence_block_id INTEGER NOT NULL,
    message_id TEXT NOT NULL,
    PRIMARY KEY (evidence_block_id, message_id),
    FOREIGN KEY (evidence_block_id, message_id)
        REFERENCES evidence_block_message(evidence_block_id, message_id) ON DELETE CASCADE
);
CREATE TABLE working_corpus_revision_evidence_block (
    working_corpus_revision_id INTEGER NOT NULL REFERENCES working_corpus_revision(working_corpus_revision_id) ON DELETE RESTRICT,
    evidence_block_id INTEGER NOT NULL REFERENCES evidence_block(evidence_block_id) ON DELETE CASCADE,
    inherited_from_revision_id INTEGER REFERENCES working_corpus_revision(working_corpus_revision_id) ON DELETE RESTRICT,
    associated_at TEXT NOT NULL,
    PRIMARY KEY (working_corpus_revision_id, evidence_block_id)
);
CREATE INDEX idx_evidence_block_dataset_thread ON evidence_block(dataset_id, source_thread_id);

CREATE TABLE conversation (
    conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    working_corpus_id INTEGER NOT NULL,
    working_corpus_revision_id INTEGER NOT NULL,
    index_generation INTEGER NOT NULL,
    scope_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'accepted',
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id) ON DELETE RESTRICT,
    FOREIGN KEY (working_corpus_id, working_corpus_revision_id)
        REFERENCES working_corpus_revision(working_corpus_id, working_corpus_revision_id) ON DELETE RESTRICT
);
CREATE TABLE conversation_turn (
    conversation_turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversation(conversation_id) ON DELETE CASCADE,
    working_corpus_id INTEGER NOT NULL,
    working_corpus_revision_id INTEGER NOT NULL,
    index_generation INTEGER NOT NULL,
    scope_hash TEXT NOT NULL,
    user_prompt TEXT NOT NULL,
    presented_answer TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'presented',
    created_at TEXT NOT NULL
);
CREATE TABLE conversation_citation (
    conversation_citation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_turn_id INTEGER NOT NULL REFERENCES conversation_turn(conversation_turn_id) ON DELETE CASCADE,
    message_id TEXT NOT NULL REFERENCES message(message_id) ON DELETE RESTRICT,
    citation_type TEXT NOT NULL DEFAULT 'cited'
);

CREATE TABLE printable_artifact_group (
    printable_artifact_group_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_collapsed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id) ON DELETE CASCADE
);
CREATE TABLE printable_artifact (
    printable_artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    exhibit_number TEXT NOT NULL DEFAULT '',
    case_number TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id) ON DELETE CASCADE,
    FOREIGN KEY (group_id) REFERENCES printable_artifact_group(printable_artifact_group_id) ON DELETE RESTRICT
);
CREATE TABLE printable_artifact_evidence_block (
    printable_artifact_evidence_block_id INTEGER PRIMARY KEY AUTOINCREMENT,
    printable_artifact_id INTEGER NOT NULL,
    evidence_block_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (printable_artifact_id) REFERENCES printable_artifact(printable_artifact_id) ON DELETE CASCADE,
    FOREIGN KEY (evidence_block_id) REFERENCES evidence_block(evidence_block_id) ON DELETE RESTRICT
);

CREATE VIRTUAL TABLE message_fts USING fts5(
    message_id UNINDEXED,
    working_corpus_revision_id UNINDEXED,
    index_generation UNINDEXED,
    source_thread_id UNINDEXED,
    body,
    body_normalized,
    sender_display,
    tokenize = 'trigram'
);
CREATE TABLE message_spellfix_term (
    working_corpus_revision_id INTEGER NOT NULL,
    index_generation INTEGER NOT NULL,
    term TEXT NOT NULL,
    rank INTEGER NOT NULL DEFAULT 1,
    document_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (working_corpus_revision_id, index_generation, term)
);

CREATE TRIGGER revision_definition_immutable
BEFORE UPDATE OF working_corpus_id, revision_number, base_revision_id, selection_mode, start_date, end_date, token_limit, dataset_content_revision
ON working_corpus_revision
WHEN OLD.status <> 'draft'
BEGIN SELECT RAISE(ABORT, 'frozen working corpus revision definition is immutable'); END;
CREATE TRIGGER revision_membership_insert_only_building
BEFORE INSERT ON working_corpus_revision_message
WHEN (SELECT status FROM working_corpus_revision WHERE working_corpus_revision_id = NEW.working_corpus_revision_id) <> 'building'
BEGIN SELECT RAISE(ABORT, 'revision membership may be written only while building'); END;
CREATE TRIGGER revision_membership_update_frozen
BEFORE UPDATE ON working_corpus_revision_message
WHEN (SELECT status FROM working_corpus_revision WHERE working_corpus_revision_id = OLD.working_corpus_revision_id) <> 'building'
BEGIN SELECT RAISE(ABORT, 'frozen revision membership is immutable'); END;
CREATE TRIGGER revision_membership_delete_frozen
BEFORE DELETE ON working_corpus_revision_message
WHEN (SELECT status FROM working_corpus_revision WHERE working_corpus_revision_id = OLD.working_corpus_revision_id) <> 'building'
BEGIN SELECT RAISE(ABORT, 'frozen revision membership is immutable'); END;
CREATE TRIGGER revision_source_insert_draft
BEFORE INSERT ON working_corpus_revision_source
WHEN (SELECT status FROM working_corpus_revision WHERE working_corpus_revision_id = NEW.working_corpus_revision_id) <> 'draft'
BEGIN SELECT RAISE(ABORT, 'revision definition is editable only while draft'); END;
CREATE TRIGGER revision_thread_insert_draft
BEFORE INSERT ON working_corpus_revision_thread
WHEN (SELECT status FROM working_corpus_revision WHERE working_corpus_revision_id = NEW.working_corpus_revision_id) <> 'draft'
BEGIN SELECT RAISE(ABORT, 'revision definition is editable only while draft'); END;
"""

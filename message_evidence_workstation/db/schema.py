"""SQLite DDL for first-wave tables."""

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset (
    dataset_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    import_validity TEXT NOT NULL DEFAULT 'ready',
    import_error TEXT NOT NULL DEFAULT '',
    normalized_format_version INTEGER
);

CREATE TABLE IF NOT EXISTS source_thread (
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
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id)
);

CREATE TABLE IF NOT EXISTS message (
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
    has_attachment INTEGER NOT NULL DEFAULT 0,
    attachment_summary TEXT NOT NULL DEFAULT '',
    sort_index INTEGER NOT NULL,
    source_metadata_json TEXT NOT NULL DEFAULT '{}',
    thread_ordinal INTEGER,
    PRIMARY KEY (dataset_id, message_id),
    FOREIGN KEY (dataset_id, source_thread_id)
        REFERENCES source_thread(dataset_id, source_thread_id)
);

CREATE TABLE IF NOT EXISTS category (
    category_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '',
    is_collapsed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id)
);

CREATE TABLE IF NOT EXISTS prompt_template (
    prompt_template_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    run_type TEXT NOT NULL,
    body TEXT NOT NULL,
    version INTEGER NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_run (
    model_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER,
    run_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_template_id INTEGER,
    input_summary TEXT NOT NULL DEFAULT '',
    raw_request_json TEXT NOT NULL DEFAULT '{}',
    raw_response_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    latency_ms INTEGER,
    error_type TEXT,
    error_message TEXT,
    stack_trace TEXT,
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id),
    FOREIGN KEY (prompt_template_id) REFERENCES prompt_template(prompt_template_id)
);

CREATE TABLE IF NOT EXISTS embedding_index_metadata (
    embedding_index_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    granularity TEXT NOT NULL,
    backend TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_revision TEXT NOT NULL DEFAULT '',
    dimensions INTEGER,
    distance_metric TEXT NOT NULL DEFAULT 'cosine',
    normalization_mode TEXT NOT NULL DEFAULT '',
    chunking_config_json TEXT NOT NULL DEFAULT '{}',
    sqlite_vec_version TEXT NOT NULL DEFAULT '',
    extension_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    last_embedded_source_thread_id TEXT NOT NULL DEFAULT '',
    last_embedded_timestamp TEXT NOT NULL DEFAULT '',
    last_embedded_sort_index INTEGER NOT NULL DEFAULT -1,
    last_embedded_message_id TEXT NOT NULL DEFAULT '',
    last_embedded_chunk_checksum TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id)
);

CREATE TABLE IF NOT EXISTS process_log (
    process_log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER,
    timestamp TEXT NOT NULL,
    severity TEXT NOT NULL,
    component TEXT NOT NULL,
    operation TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    exception_type TEXT,
    stack_trace TEXT,
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id)
);

CREATE INDEX IF NOT EXISTS idx_message_thread_order
    ON message(dataset_id, source_thread_id, timestamp, sort_index);

CREATE INDEX IF NOT EXISTS idx_process_log_timestamp
    ON process_log(timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_category_dataset
    ON category(dataset_id);

CREATE TABLE IF NOT EXISTS workspace_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_block (
    evidence_block_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    source_thread_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    core_hit_message_id TEXT NOT NULL,
    context_start_slot INTEGER NOT NULL,
    relevant_start_slot INTEGER NOT NULL,
    relevant_end_slot INTEGER NOT NULL,
    context_end_slot INTEGER NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id),
    FOREIGN KEY (category_id) REFERENCES category(category_id)
);

CREATE TABLE IF NOT EXISTS evidence_block_highlight (
    evidence_block_id INTEGER NOT NULL,
    message_id TEXT NOT NULL,
    PRIMARY KEY (evidence_block_id, message_id),
    FOREIGN KEY (evidence_block_id) REFERENCES evidence_block(evidence_block_id)
);

CREATE INDEX IF NOT EXISTS idx_evidence_block_dataset_thread
    ON evidence_block(dataset_id, source_thread_id);

CREATE INDEX IF NOT EXISTS idx_evidence_block_category
    ON evidence_block(category_id);

CREATE TABLE IF NOT EXISTS transcript_session (
    session_id TEXT NOT NULL,
    dataset_id INTEGER NOT NULL,
    source_thread_id TEXT NOT NULL,
    session_index INTEGER NOT NULL,
    calendar_date TEXT NOT NULL,
    start_message_id TEXT NOT NULL,
    end_message_id TEXT NOT NULL,
    start_timestamp TEXT NOT NULL,
    end_timestamp TEXT NOT NULL,
    participants_json TEXT NOT NULL DEFAULT '[]',
    message_count INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'built',
    summary_json TEXT NOT NULL DEFAULT '{}',
    summary_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (dataset_id, session_id),
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id)
);

CREATE INDEX IF NOT EXISTS idx_transcript_session_dataset_thread
    ON transcript_session(dataset_id, source_thread_id, session_index);

CREATE TABLE IF NOT EXISTS printable_artifact_group (
    printable_artifact_group_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_collapsed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id)
);

CREATE TABLE IF NOT EXISTS printable_artifact (
    printable_artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    exhibit_number TEXT NOT NULL DEFAULT '',
    case_number TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id),
    FOREIGN KEY (group_id) REFERENCES printable_artifact_group(printable_artifact_group_id)
);

CREATE TABLE IF NOT EXISTS printable_artifact_evidence_block (
    printable_artifact_evidence_block_id INTEGER PRIMARY KEY AUTOINCREMENT,
    printable_artifact_id INTEGER NOT NULL,
    evidence_block_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (printable_artifact_id) REFERENCES printable_artifact(printable_artifact_id),
    FOREIGN KEY (evidence_block_id) REFERENCES evidence_block(evidence_block_id)
);

CREATE INDEX IF NOT EXISTS idx_printable_artifact_group_dataset
    ON printable_artifact_group(dataset_id, sort_order);

CREATE INDEX IF NOT EXISTS idx_printable_artifact_group
    ON printable_artifact(group_id, sort_order);

CREATE INDEX IF NOT EXISTS idx_printable_artifact_evidence_block_artifact
    ON printable_artifact_evidence_block(printable_artifact_id, sort_order);
"""

# FTS virtual table created in T06; placeholder comment only here.

"""FTS5 virtual table DDL."""

MESSAGE_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
    message_id UNINDEXED,
    dataset_id UNINDEXED,
    source_thread_id UNINDEXED,
    body,
    body_normalized,
    sender_display,
    tokenize = 'unicode61'
);
"""

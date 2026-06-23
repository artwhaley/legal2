"""Normalized dataset loader tests."""

import json
from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.evidence_blocks import create_evidence_block_from_search, ensure_uncategorized_category
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.repositories import list_messages_for_thread
from message_evidence_workstation.importers.normalized_loader import (
    DatasetLoadError,
    load_normalized_dataset,
    normalize_body,
)
from message_evidence_workstation.logging_ui.process_log import ProcessLogger


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def loaded_db(tmp_path):
    conn = connect(tmp_path / "test.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_normalize_body() -> None:
    assert normalize_body("  Hello   WORLD ") == "hello world"


def test_load_sample_fixture_counts(loaded_db) -> None:
    conn, _logger, dataset_id = loaded_db
    thread_count = conn.execute(
        "SELECT COUNT(*) FROM source_thread WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchone()[0]
    message_count = conn.execute(
        "SELECT COUNT(*) FROM message WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchone()[0]
    assert thread_count == 1
    assert message_count == 100


def test_messages_sorted_by_thread_timestamp_and_sort_index(loaded_db) -> None:
    conn, _logger, dataset_id = loaded_db
    rows = conn.execute(
        """
        SELECT message_id, timestamp, sort_index
        FROM message
        WHERE dataset_id = ? AND source_thread_id = 'thread_001'
        ORDER BY timestamp, sort_index, message_id
        """,
        (dataset_id,),
    ).fetchall()
    assert [row["message_id"] for row in rows[:3]] == ["msg_001", "msg_002", "msg_003"]
    assert len(rows) == 100


def test_malformed_jsonl_reports_line_number(tmp_path) -> None:
    dataset_dir = tmp_path / "bad_dataset"
    dataset_dir.mkdir()
    (dataset_dir / "dataset.json").write_text(json.dumps({"name": "Bad"}), encoding="utf-8")
    (dataset_dir / "source_threads.jsonl").write_text("", encoding="utf-8")
    (dataset_dir / "messages.jsonl").write_text("{not json\n", encoding="utf-8")

    conn = connect(tmp_path / "test.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    with pytest.raises(DatasetLoadError) as exc_info:
        load_normalized_dataset(conn, logger, dataset_dir)
    assert exc_info.value.line_number == 1
    assert exc_info.value.file == "messages.jsonl"


def test_missing_required_field(tmp_path) -> None:
    dataset_dir = tmp_path / "missing_field"
    dataset_dir.mkdir()
    (dataset_dir / "dataset.json").write_text(json.dumps({"name": "Bad"}), encoding="utf-8")
    (dataset_dir / "source_threads.jsonl").write_text(
        json.dumps({"source_thread_id": "t1"}),
        encoding="utf-8",
    )
    (dataset_dir / "messages.jsonl").write_text("", encoding="utf-8")

    conn = connect(tmp_path / "test.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    with pytest.raises(DatasetLoadError):
        load_normalized_dataset(conn, logger, dataset_dir)


def test_reload_is_idempotent_with_skip(loaded_db) -> None:
    conn, logger, dataset_id = loaded_db
    again = load_normalized_dataset(conn, logger, FIXTURE_DIR, reload=False)
    assert again == dataset_id
    message_count = conn.execute("SELECT COUNT(*) FROM message").fetchone()[0]
    assert message_count == 100


def test_reload_clears_dataset_with_audit_rows(loaded_db) -> None:
    conn, logger, dataset_id = loaded_db
    conn.execute(
        """
        INSERT INTO model_run (
            dataset_id, run_type, provider, model, created_at
        ) VALUES (?, 'keyword_expansion', 'nvidia_nim', 'test-model', '2024-01-01T00:00:00+00:00')
        """,
        (dataset_id,),
    )
    conn.execute(
        """
        INSERT INTO embedding_index_metadata (
            dataset_id, granularity, backend, model_name, created_at, status
        ) VALUES (?, 'message', 'sqlite_vec', 'test-model', '2024-01-01T00:00:00+00:00', 'ready')
        """,
        (dataset_id,),
    )
    conn.commit()
    reloaded_id = load_normalized_dataset(conn, logger, FIXTURE_DIR, reload=True)
    assert reloaded_id != dataset_id
    assert conn.execute("SELECT COUNT(*) FROM message").fetchone()[0] == 100
    assert conn.execute("SELECT COUNT(*) FROM model_run WHERE dataset_id = ?", (dataset_id,)).fetchone()[0] == 0


def test_reload_clears_persisted_evidence_blocks_before_categories(loaded_db) -> None:
    conn, logger, dataset_id = loaded_db
    category = ensure_uncategorized_category(conn, logger, dataset_id)
    messages = list_messages_for_thread(conn, dataset_id, "thread_001")
    create_evidence_block_from_search(
        conn,
        logger,
        dataset_id=dataset_id,
        source_thread_id="thread_001",
        primary_hit_message_id="msg_001",
        title="Reload safety",
        ordered_message_ids=[message.message_id for message in messages],
        category_id=category.category_id,
    )

    reloaded_id = load_normalized_dataset(conn, logger, FIXTURE_DIR, reload=True)

    assert reloaded_id != dataset_id
    assert conn.execute("SELECT COUNT(*) FROM category WHERE dataset_id = ?", (dataset_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM evidence_block WHERE dataset_id = ?", (dataset_id,)).fetchone()[0] == 0


def test_reload_preserves_embedding_rows(loaded_db) -> None:
    conn, logger, dataset_id = loaded_db
    from message_evidence_workstation.embeddings.sqlite_vec_backend import (
        CHUNK_VEC_TABLE,
        MESSAGE_VEC_TABLE,
        ensure_chunk_metadata_schema,
        ensure_chunk_vec_table,
        ensure_message_vec_table,
        insert_chunk_vectors,
        insert_message_vectors,
        load_sqlite_vec,
    )

    load_sqlite_vec(conn)
    ensure_message_vec_table(conn, 4)
    ensure_chunk_metadata_schema(conn)
    ensure_chunk_vec_table(conn, 4)
    insert_message_vectors(
        conn,
        [([0.1, 0.2, 0.3, 0.4], "msg_001", dataset_id, "thread_001")],
    )
    cursor = conn.execute(
        """
        INSERT INTO message_chunk (
            dataset_id, source_thread_id, start_message_id, end_message_id,
            message_count, char_count, text_checksum, body_text
        ) VALUES (?, 'thread_001', 'msg_001', 'msg_001', 1, 3, 'abc', 'hi')
        """,
        (dataset_id,),
    )
    chunk_id = int(cursor.lastrowid)
    insert_chunk_vectors(conn, [([0.1, 0.2, 0.3, 0.4], chunk_id, dataset_id, "thread_001")])
    conn.execute(
        """
        INSERT INTO embedding_index_metadata (
            dataset_id, granularity, backend, model_name, dimensions, created_at, status,
            message_count, chunk_count
        ) VALUES (?, 'message', 'sqlite_vec', 'test-model', 4, '2024-01-01T00:00:00+00:00', 'ready', 1, 0)
        """,
        (dataset_id,),
    )
    conn.commit()

    reloaded_id = load_normalized_dataset(conn, logger, FIXTURE_DIR, reload=True)
    assert reloaded_id != dataset_id
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM message_embedding_vec WHERE dataset_id = ?",
            (reloaded_id,),
        ).fetchone()[0]
        == 1
    )
    assert conn.execute("SELECT COUNT(*) FROM message_chunk WHERE dataset_id = ?", (reloaded_id,)).fetchone()[0] == 1
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE name = ?", (CHUNK_VEC_TABLE,)
    ).fetchone():
        assert (
            conn.execute(
                f"SELECT COUNT(*) FROM {CHUNK_VEC_TABLE} WHERE dataset_id = ?",
                (reloaded_id,),
            ).fetchone()[0]
            == 1
        )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM embedding_index_metadata WHERE dataset_id = ? AND status = 'ready'",
            (reloaded_id,),
        ).fetchone()[0]
        >= 1
    )

"""Normalized dataset loader tests."""

import json
from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.evidence_blocks import create_evidence_block_from_search, ensure_uncategorized_category
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.repositories import list_messages_for_thread
from message_evidence_workstation.domain.constants import (
    IMPORT_VALIDITY_FAILED,
    IMPORT_VALIDITY_READY,
    NORMALIZED_FORMAT_VERSION,
)
from message_evidence_workstation.importers.normalized_loader import (
    DatasetLoadError,
    INSERT_BATCH_SIZE,
    get_dataset_import_validity,
    get_workspace_import_validity,
    load_normalized_dataset,
    normalize_body,
)
from message_evidence_workstation.logging_ui.process_log import ProcessLogger


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


def _write_chunked_dataset(
    dataset_dir: Path,
    *,
    message_count: int,
    name: str = "Chunked Dataset",
) -> None:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    (dataset_dir / "dataset.json").write_text(
        json.dumps(
            {
                "name": name,
                "normalized_format_version": NORMALIZED_FORMAT_VERSION,
            }
        ),
        encoding="utf-8",
    )
    thread = {
        "source_thread_id": "thread_chunk",
        "source_platform": "messenger",
        "platform_thread_id": "chunk-thread",
        "display_title": "Chunk Test",
        "participant_summary": "A, B",
        "start_ts": "2024-01-01T08:00:00+00:00",
        "end_ts": "2024-01-02T08:00:00+00:00",
        "metadata_json": {},
    }
    (dataset_dir / "source_threads.jsonl").write_text(
        json.dumps(thread) + "\n",
        encoding="utf-8",
    )
    message_lines = []
    for index in range(1, message_count + 1):
        message_lines.append(
            json.dumps(
                {
                    "message_id": f"msg_{index:05d}",
                    "source_thread_id": "thread_chunk",
                    "source_platform": "messenger",
                    "source_message_id": f"chunk-{index}",
                    "timestamp": "2024-01-01T08:00:00+00:00",
                    "sender_id": "a",
                    "sender_display": "A",
                    "body": f"Message {index}",
                    "has_attachment": False,
                    "attachment_summary": "",
                    "sort_index": index,
                    "source_metadata_json": {},
                }
            )
        )
    (dataset_dir / "messages.jsonl").write_text("\n".join(message_lines) + "\n", encoding="utf-8")


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
    assert get_dataset_import_validity(conn, dataset_id) == IMPORT_VALIDITY_READY
    assert get_workspace_import_validity(conn) == IMPORT_VALIDITY_READY
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
    failed = conn.execute(
        "SELECT import_validity, import_error FROM dataset ORDER BY dataset_id DESC LIMIT 1"
    ).fetchone()
    assert failed is not None
    assert failed["import_validity"] == IMPORT_VALIDITY_FAILED
    assert failed["import_error"]
    assert get_workspace_import_validity(conn) == IMPORT_VALIDITY_FAILED


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
    failed = conn.execute(
        "SELECT import_validity FROM dataset ORDER BY dataset_id DESC LIMIT 1"
    ).fetchone()
    assert failed is not None
    assert failed["import_validity"] == IMPORT_VALIDITY_FAILED


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
        model_name="test-model",
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
    insert_chunk_vectors(
        conn,
        [([0.1, 0.2, 0.3, 0.4], chunk_id, dataset_id, "thread_001")],
        model_name="test-model",
    )
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


def test_batched_insert_multi_chunk(tmp_path) -> None:
    message_count = INSERT_BATCH_SIZE + 100
    dataset_dir = tmp_path / "chunked"
    _write_chunked_dataset(dataset_dir, message_count=message_count)

    conn = connect(tmp_path / "test.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, dataset_dir)

    stored = conn.execute(
        "SELECT COUNT(*) FROM message WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchone()[0]
    assert stored == message_count
    assert get_dataset_import_validity(conn, dataset_id) == IMPORT_VALIDITY_READY


def test_failed_import_after_threads_does_not_mark_ready(tmp_path) -> None:
    dataset_dir = tmp_path / "partial_fail"
    dataset_dir.mkdir()
    (dataset_dir / "dataset.json").write_text(json.dumps({"name": "Partial Fail"}), encoding="utf-8")
    (dataset_dir / "source_threads.jsonl").write_text(
        json.dumps(
            {
                "source_thread_id": "t1",
                "source_platform": "messenger",
                "platform_thread_id": "p1",
                "display_title": "T",
                "start_ts": "2024-01-01T08:00:00+00:00",
                "end_ts": "2024-01-01T09:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    good = json.dumps(
        {
            "message_id": "m1",
            "source_thread_id": "t1",
            "source_platform": "messenger",
            "source_message_id": "s1",
            "timestamp": "2024-01-01T08:00:00+00:00",
            "sender_id": "a",
            "sender_display": "A",
            "body": "ok",
            "sort_index": 1,
        }
    )
    (dataset_dir / "messages.jsonl").write_text(good + "\n{not json}\n", encoding="utf-8")

    conn = connect(tmp_path / "test.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    with pytest.raises(DatasetLoadError) as exc_info:
        load_normalized_dataset(conn, logger, dataset_dir)
    assert exc_info.value.file == "messages.jsonl"
    assert exc_info.value.line_number == 2

    row = conn.execute(
        "SELECT dataset_id, import_validity, import_error FROM dataset ORDER BY dataset_id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["import_validity"] == IMPORT_VALIDITY_FAILED
    assert row["import_error"]
    assert get_workspace_import_validity(conn) == IMPORT_VALIDITY_FAILED
    assert (
        conn.execute("SELECT COUNT(*) FROM source_thread WHERE dataset_id = ?", (row["dataset_id"],)).fetchone()[0]
        == 1
    )
    assert conn.execute("SELECT COUNT(*) FROM message WHERE dataset_id = ?", (row["dataset_id"],)).fetchone()[0] == 0


def test_normalized_format_version_rejects_mismatch(tmp_path) -> None:
    dataset_dir = tmp_path / "bad_version"
    dataset_dir.mkdir()
    (dataset_dir / "dataset.json").write_text(
        json.dumps({"name": "Bad Version", "normalized_format_version": 999}),
        encoding="utf-8",
    )
    (dataset_dir / "source_threads.jsonl").write_text("", encoding="utf-8")
    (dataset_dir / "messages.jsonl").write_text("", encoding="utf-8")

    conn = connect(tmp_path / "test.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    with pytest.raises(DatasetLoadError) as exc_info:
        load_normalized_dataset(conn, logger, dataset_dir)
    assert exc_info.value.file == "dataset.json"
    assert conn.execute("SELECT COUNT(*) FROM dataset").fetchone()[0] == 0


def test_progress_callback_reports_phases(tmp_path) -> None:
    dataset_dir = tmp_path / "progress"
    _write_chunked_dataset(dataset_dir, message_count=5, name="Progress Dataset")

    conn = connect(tmp_path / "test.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    events: list[tuple[str, int, int]] = []

    def on_progress(phase: str, lines_read: int, lines_written: int) -> None:
        events.append((phase, lines_read, lines_written))

    load_normalized_dataset(conn, logger, dataset_dir, progress_callback=on_progress)

    phases = [phase for phase, _read, _written in events]
    assert "threads" in phases
    assert "messages" in phases
    assert "fts" in phases
    assert "spellfix" in phases
    assert "sessions" in phases
    assert events[-1][2] >= events[0][2]


def test_post_import_steps_use_baseline_sessions_without_semantic_chunking(tmp_path, monkeypatch) -> None:
    dataset_dir = tmp_path / "baseline_sessions"
    _write_chunked_dataset(dataset_dir, message_count=5, name="Baseline Sessions Dataset")

    conn = connect(tmp_path / "test.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)

    def fail_semantic_chunking(*_args, **_kwargs):
        raise AssertionError("normalized loader post-import steps must not use semantic chunking")

    monkeypatch.setattr(
        "message_evidence_workstation.search.session_map.iter_dataset_chunks",
        fail_semantic_chunking,
    )

    dataset_id = load_normalized_dataset(conn, logger, dataset_dir)

    rows = conn.execute(
        "SELECT start_message_id, end_message_id, message_count FROM transcript_session WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchall()
    assert rows
    assert all(row["start_message_id"] and row["end_message_id"] for row in rows)
    assert all(int(row["message_count"]) > 0 for row in rows)

"""Resumable embedding index build tests."""

from pathlib import Path

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.embeddings.adapters import FakeEmbeddingAdapter
from message_evidence_workstation.embeddings.index_jobs import (
    BATCH_SIZE,
    build_message_embedding_index,
    get_ready_index,
)
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


def test_message_index_resumes_after_partial_build(tmp_path) -> None:
    conn = connect(tmp_path / "resume.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)

    adapter = FakeEmbeddingAdapter(model_name="fake-resume", dimensions=8)
    info = adapter.load()

    rows = conn.execute(
        "SELECT message_id, source_thread_id, body_normalized FROM message WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchall()
    first_batch = rows[:BATCH_SIZE]
    from message_evidence_workstation.embeddings.sqlite_vec_backend import (
        ensure_message_vec_table,
        insert_message_vectors,
        load_sqlite_vec,
    )

    load_sqlite_vec(conn)
    ensure_message_vec_table(conn, info.dimensions)
    vectors = adapter.embed_texts([row["body_normalized"] for row in first_batch])
    insert_message_vectors(
        conn,
        [
            (vector, row["message_id"], dataset_id, row["source_thread_id"])
            for vector, row in zip(vectors, first_batch, strict=True)
        ],
    )
    conn.execute(
        """
        INSERT INTO embedding_index_metadata (
            dataset_id, granularity, backend, model_name, model_revision, dimensions,
            distance_metric, normalization_mode, chunking_config_json, sqlite_vec_version,
            extension_path, created_at, status, message_count, chunk_count, last_error
        ) VALUES (?, 'message', 'sqlite_vec', ?, '', ?, 'cosine', '', '{}', '', 'auto', 'now', 'building', ?, 0, '')
        """,
        (dataset_id, info.model_name, info.dimensions, len(first_batch)),
    )
    conn.commit()

    result = build_message_embedding_index(
        conn,
        logger,
        dataset_id=dataset_id,
        adapter=adapter,
        adapter_info=info,
    )
    assert result.success, result.error
    assert result.resumed
    assert result.count == len(rows)
    assert get_ready_index(conn, dataset_id, "message", "fake-resume") is not None


def test_message_index_skips_when_already_complete(tmp_path) -> None:
    conn = connect(tmp_path / "complete.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    adapter = FakeEmbeddingAdapter(model_name="fake-complete", dimensions=8)
    info = adapter.load()
    first = build_message_embedding_index(
        conn,
        logger,
        dataset_id=dataset_id,
        adapter=adapter,
        adapter_info=info,
    )
    assert first.success, first.error
    second = build_message_embedding_index(
        conn,
        logger,
        dataset_id=dataset_id,
        adapter=adapter,
        adapter_info=info,
    )
    assert second.success, second.error
    assert second.resumed
    assert second.elapsed_ms == 0
    assert second.count == first.count


def test_message_index_logs_batch_progress(tmp_path) -> None:
    conn = connect(tmp_path / "progress.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    adapter = FakeEmbeddingAdapter(model_name="fake-progress", dimensions=8)
    info = adapter.load()
    build_message_embedding_index(
        conn,
        logger,
        dataset_id=dataset_id,
        adapter=adapter,
        adapter_info=info,
    )
    row = conn.execute(
        """
        SELECT message FROM process_log
        WHERE operation = 'message_batch_progress'
        ORDER BY process_log_id DESC
        LIMIT 1
        """
    ).fetchone()
    assert row is not None
    assert "batch" in row["message"].lower()

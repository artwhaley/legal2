"""Resumable embedding index build tests."""

from pathlib import Path

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.embeddings.adapters import FakeEmbeddingAdapter
from message_evidence_workstation.embeddings.index_jobs import (
    BATCH_SIZE,
    MessageSortKey,
    build_message_embedding_index,
    get_ready_index,
)
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


def _partial_message_build(conn, logger, dataset_id, adapter, info, batch_count: int = 1) -> list:
    from message_evidence_workstation.embeddings.sqlite_vec_backend import (
        ensure_message_vec_table,
        insert_message_vectors,
        load_sqlite_vec,
    )

    rows = conn.execute(
        """
        SELECT message_id, source_thread_id, body_normalized, timestamp, sort_index
        FROM message
        WHERE dataset_id = ?
        ORDER BY source_thread_id, timestamp, sort_index, message_id
        """,
        (dataset_id,),
    ).fetchall()
    embedded_rows = rows[: batch_count * BATCH_SIZE]
    load_sqlite_vec(conn)
    ensure_message_vec_table(conn, info.dimensions)
    vectors = adapter.embed_texts([row["body_normalized"] for row in embedded_rows])
    insert_message_vectors(
        conn,
        [
            (vector, row["message_id"], dataset_id, row["source_thread_id"])
            for vector, row in zip(vectors, embedded_rows, strict=True)
        ],
        model_name=info.model_name,
    )
    last_row = embedded_rows[-1]
    sort_key = MessageSortKey.from_row(last_row)
    conn.execute(
        """
        INSERT INTO embedding_index_metadata (
            dataset_id, granularity, backend, model_name, model_revision, dimensions,
            distance_metric, normalization_mode, chunking_config_json, sqlite_vec_version,
            extension_path, created_at, status, message_count, chunk_count, last_error,
            last_embedded_source_thread_id, last_embedded_timestamp, last_embedded_sort_index,
            last_embedded_message_id, last_embedded_chunk_checksum
        ) VALUES (?, 'message', 'sqlite_vec', ?, ?, ?, 'cosine', ?, '{}', '', 'auto', 'now',
                  'building', ?, 0, '', ?, ?, ?, ?, '')
        """,
        (
            dataset_id,
            info.model_name,
            info.model_revision,
            info.dimensions,
            info.normalization_mode,
            len(embedded_rows),
            *sort_key.as_tuple(),
        ),
    )
    conn.commit()
    return rows


def test_message_index_resumes_after_partial_build(tmp_path) -> None:
    conn = connect(tmp_path / "resume.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)

    adapter = FakeEmbeddingAdapter(model_name="fake-resume", dimensions=8)
    info = adapter.load()
    rows = _partial_message_build(conn, logger, dataset_id, adapter, info)

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
    assert result.resume_strategy in {"checkpoint", "hole_fill", "antijoin"}
    assert get_ready_index(conn, dataset_id, "message", "fake-resume") is not None


def test_message_index_resumes_with_checkpoint_fast_path(tmp_path) -> None:
    conn = connect(tmp_path / "checkpoint.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)

    adapter = FakeEmbeddingAdapter(model_name="fake-checkpoint", dimensions=8)
    info = adapter.load()
    rows = _partial_message_build(conn, logger, dataset_id, adapter, info, batch_count=2)

    result = build_message_embedding_index(
        conn,
        logger,
        dataset_id=dataset_id,
        adapter=adapter,
        adapter_info=info,
    )
    assert result.success, result.error
    assert result.resume_strategy == "checkpoint"
    assert result.count == len(rows)


def test_message_index_fills_hole_after_deleted_embedding(tmp_path) -> None:
    conn = connect(tmp_path / "hole.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)

    adapter = FakeEmbeddingAdapter(model_name="fake-hole", dimensions=8)
    info = adapter.load()
    rows = _partial_message_build(conn, logger, dataset_id, adapter, info, batch_count=3)

    hole_row = conn.execute(
        """
        SELECT message_id FROM message
        WHERE dataset_id = ?
        ORDER BY source_thread_id, timestamp, sort_index, message_id
        LIMIT 1
        """,
        (dataset_id,),
    ).fetchone()
    conn.execute(
        "DELETE FROM message_embedding_vec WHERE dataset_id = ? AND message_id = ?",
        (dataset_id, hole_row["message_id"]),
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
    assert result.resume_strategy == "hole_fill"
    assert result.count == len(rows)
    stored = conn.execute(
        "SELECT COUNT(*) FROM message_embedding_vec WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchone()[0]
    assert stored == len(rows)


def test_model_settings_change_invalidates_checkpoint(tmp_path) -> None:
    conn = connect(tmp_path / "model-change.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)

    adapter = FakeEmbeddingAdapter(model_name="fake-model-change", dimensions=8)
    info = adapter.load()
    _partial_message_build(conn, logger, dataset_id, adapter, info)

    changed = FakeEmbeddingAdapter(model_name="fake-model-change", dimensions=16)
    changed_info = changed.load()

    result = build_message_embedding_index(
        conn,
        logger,
        dataset_id=dataset_id,
        adapter=changed,
        adapter_info=changed_info,
    )
    assert result.success, result.error
    assert result.count == 100
    assert not result.resumed


def test_resume_avoids_full_embedded_id_set_load(tmp_path, monkeypatch) -> None:
    conn = connect(tmp_path / "memory.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)

    adapter = FakeEmbeddingAdapter(model_name="fake-memory", dimensions=8)
    info = adapter.load()
    _partial_message_build(conn, logger, dataset_id, adapter, info, batch_count=2)

    import message_evidence_workstation.embeddings.index_jobs as index_jobs

    calls = {"count": 0}

    def _forbidden(*_args, **_kwargs):
        calls["count"] += 1
        raise AssertionError("_embedded_message_ids must not be used on resume paths")

    monkeypatch.setattr(index_jobs, "_embedded_message_ids", _forbidden)

    result = build_message_embedding_index(
        conn,
        logger,
        dataset_id=dataset_id,
        adapter=adapter,
        adapter_info=info,
    )
    assert result.success, result.error
    assert calls["count"] == 0


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

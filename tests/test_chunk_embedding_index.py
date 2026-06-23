"""Chunk embedding index tests."""

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.embeddings.adapters import FakeEmbeddingAdapter
from message_evidence_workstation.embeddings.chunking import ChunkingConfig
from message_evidence_workstation.embeddings.index_jobs import (
    build_chunk_embedding_index,
    build_message_embedding_index,
    get_ready_index,
)
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def index_db(tmp_path):
    conn = connect(tmp_path / "chunk_index.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_chunk_index_build_with_fake_adapter(index_db) -> None:
    conn, logger, dataset_id = index_db
    adapter = FakeEmbeddingAdapter(model_name="fake-chunk", dimensions=8)
    info = adapter.load()
    message_result = build_message_embedding_index(
        conn,
        logger,
        dataset_id=dataset_id,
        adapter=adapter,
        adapter_info=info,
    )
    assert message_result.success, message_result.error
    result = build_chunk_embedding_index(
        conn,
        logger,
        dataset_id=dataset_id,
        adapter=adapter,
        adapter_info=info,
    )
    assert result.success, result.error
    assert result.count >= 2
    row = get_ready_index(conn, dataset_id, "chunk", "fake-chunk")
    assert row is not None
    stored = conn.execute(
        "SELECT COUNT(*) FROM chunk_embedding_vec WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchone()[0]
    assert stored == result.count


def test_semantic_chunk_index_requires_message_embeddings(index_db) -> None:
    conn, logger, dataset_id = index_db
    adapter = FakeEmbeddingAdapter(model_name="fake-chunk-missing-messages", dimensions=8)
    info = adapter.load()

    result = build_chunk_embedding_index(
        conn,
        logger,
        dataset_id=dataset_id,
        adapter=adapter,
        adapter_info=info,
    )

    assert not result.success
    assert "Build message embeddings" in str(result.error)


def test_chunk_index_rebuilds_when_chunking_config_changes(index_db) -> None:
    conn, logger, dataset_id = index_db
    adapter = FakeEmbeddingAdapter(model_name="fake-chunk-config", dimensions=8)
    info = adapter.load()
    message_result = build_message_embedding_index(
        conn,
        logger,
        dataset_id=dataset_id,
        adapter=adapter,
        adapter_info=info,
    )
    assert message_result.success, message_result.error
    first = build_chunk_embedding_index(
        conn,
        logger,
        dataset_id=dataset_id,
        adapter=adapter,
        adapter_info=info,
        chunking_config=ChunkingConfig(max_chars=500, semantic_similarity_threshold=0.0, session_gap_hours=24.0),
    )
    second = build_chunk_embedding_index(
        conn,
        logger,
        dataset_id=dataset_id,
        adapter=adapter,
        adapter_info=info,
        chunking_config=ChunkingConfig(max_chars=300, semantic_similarity_threshold=0.0, session_gap_hours=24.0),
    )

    assert first.success, first.error
    assert second.success, second.error
    assert not second.resumed

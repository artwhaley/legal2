"""Per-model embedding vector partition persistence."""

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.embeddings.adapters import FakeEmbeddingAdapter
from message_evidence_workstation.embeddings.index_jobs import (
    build_message_embedding_index,
    get_ready_index,
    mark_indexes_stale_for_model_change,
)
from message_evidence_workstation.embeddings.sqlite_vec_backend import (
    _vec_table_has_model_partition,
    count_message_vectors,
    search_message_vectors,
)
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def index_db(tmp_path):
    conn = connect(tmp_path / "per_model.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_per_model_vectors_persist_and_skip_rebuild(index_db) -> None:
    conn, logger, dataset_id = index_db

    adapter_a = FakeEmbeddingAdapter(model_name="fake-model-a", dimensions=8)
    info_a = adapter_a.load()
    result_a = build_message_embedding_index(
        conn, logger, dataset_id=dataset_id, adapter=adapter_a, adapter_info=info_a
    )
    assert result_a.success, result_a.error
    assert _vec_table_has_model_partition(conn, "message_embedding_vec")
    assert count_message_vectors(conn, dataset_id, model_name="fake-model-a") == 100

    adapter_b = FakeEmbeddingAdapter(model_name="fake-model-b", dimensions=8)
    info_b = adapter_b.load()
    result_b = build_message_embedding_index(
        conn, logger, dataset_id=dataset_id, adapter=adapter_b, adapter_info=info_b
    )
    assert result_b.success, result_b.error
    assert count_message_vectors(conn, dataset_id, model_name="fake-model-b") == 100
    assert count_message_vectors(conn, dataset_id, model_name="fake-model-a") == 100

    result_a_again = build_message_embedding_index(
        conn, logger, dataset_id=dataset_id, adapter=adapter_a, adapter_info=info_a
    )
    assert result_a_again.success
    assert result_a_again.resumed
    assert result_a_again.count == 100
    assert count_message_vectors(conn, dataset_id, model_name="fake-model-a") == 100


def test_stale_metadata_does_not_delete_other_model_vectors(index_db) -> None:
    conn, logger, dataset_id = index_db
    adapter_a = FakeEmbeddingAdapter(model_name="fake-stale-a", dimensions=8)
    info_a = adapter_a.load()
    build_message_embedding_index(
        conn, logger, dataset_id=dataset_id, adapter=adapter_a, adapter_info=info_a
    )

    adapter_b = FakeEmbeddingAdapter(model_name="fake-stale-b", dimensions=8)
    info_b = adapter_b.load()
    build_message_embedding_index(
        conn, logger, dataset_id=dataset_id, adapter=adapter_b, adapter_info=info_b
    )

    mark_indexes_stale_for_model_change(conn, logger, dataset_id, "fake-stale-b")
    row = conn.execute(
        """
        SELECT status FROM embedding_index_metadata
        WHERE dataset_id = ? AND granularity = 'message' AND model_name = ?
        """,
        (dataset_id, "fake-stale-a"),
    ).fetchone()
    assert row is not None
    assert row["status"] == "stale"
    assert count_message_vectors(conn, dataset_id, model_name="fake-stale-a") == 100


def test_knn_search_scoped_to_model(index_db) -> None:
    conn, logger, dataset_id = index_db
    adapter_a = FakeEmbeddingAdapter(model_name="knn-a", dimensions=8)
    info_a = adapter_a.load()
    build_message_embedding_index(
        conn, logger, dataset_id=dataset_id, adapter=adapter_a, adapter_info=info_a
    )
    query = adapter_a.embed_texts(["allergy form"])[0]
    hits = search_message_vectors(
        conn,
        logger,
        dataset_id=dataset_id,
        query_vector=query,
        model_name="knn-a",
        top_k=5,
    )
    assert hits
    assert count_message_vectors(conn, dataset_id, model_name="knn-a") == 100
    assert count_message_vectors(conn, dataset_id, model_name="missing-model") == 0

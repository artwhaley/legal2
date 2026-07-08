"""Embedding search fusion tests."""

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.embeddings.adapters import FakeEmbeddingAdapter
from message_evidence_workstation.embeddings.sqlite_vec_backend import VectorSearchHit
from message_evidence_workstation.embeddings.index_jobs import (
    build_chunk_embedding_index,
    build_message_embedding_index,
    mark_indexes_stale_for_model_change,
)
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search.date_scope import MessageDateScope
from message_evidence_workstation.search.embedding_search import (
    EmbeddingIndexNotReadyError,
    filter_vector_hits_by_selectivity,
    resolve_embedding_selectivity,
    search_message_embeddings,
)
from message_evidence_workstation.search.fusion import fuse_hits
from message_evidence_workstation.search.result_models import SearchHit

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def search_db(tmp_path):
    conn = connect(tmp_path / "embed_search.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    adapter = FakeEmbeddingAdapter(model_name="fake-search", dimensions=8)
    info = adapter.load()
    build_message_embedding_index(conn, logger, dataset_id=dataset_id, adapter=adapter, adapter_info=info)
    return conn, logger, dataset_id, adapter


def test_message_embedding_search_returns_hits(search_db) -> None:
    conn, logger, dataset_id, adapter = search_db
    hits = search_message_embeddings(
        conn,
        logger,
        dataset_id=dataset_id,
        query="allergy",
        model_name="fake-search",
        adapter=adapter,
        top_k=3,
    )
    assert hits
    assert hits[0].match_type == "message_embedding"
    assert hits[0].distance is not None


def test_embedding_selectivity_profiles_adjust_result_squelch() -> None:
    hits = [
        VectorSearchHit("m1", "t1", distance=0.10, rank=1),
        VectorSearchHit("m2", "t1", distance=0.25, rank=2),
        VectorSearchHit("m3", "t1", distance=0.60, rank=3),
    ]

    broad = filter_vector_hits_by_selectivity(hits, "broad")
    balanced = filter_vector_hits_by_selectivity(hits, "balanced")
    narrow = filter_vector_hits_by_selectivity(hits, "narrow")

    assert resolve_embedding_selectivity("broad").top_k > resolve_embedding_selectivity("narrow").top_k
    assert [hit.message_id for hit in broad] == ["m1", "m2", "m3"]
    assert [hit.message_id for hit in balanced] == ["m1", "m2"]
    assert [hit.message_id for hit in narrow] == ["m1"]


def test_stale_index_raises(search_db) -> None:
    conn, logger, dataset_id, adapter = search_db
    mark_indexes_stale_for_model_change(conn, logger, dataset_id, "other-model")
    with pytest.raises(EmbeddingIndexNotReadyError):
        search_message_embeddings(
            conn,
            logger,
            dataset_id=dataset_id,
            query="allergy",
            model_name="fake-search",
            adapter=adapter,
        )


def test_fusion_keeps_one_row_with_multiple_methods() -> None:
    fused = fuse_hits(
        [
            SearchHit(
                message_id="m1",
                source_thread_id="t1",
                match_type="exact",
                retrieval_method="fts_exact",
                query_text="q",
            )
        ],
        [
            SearchHit(
                message_id="m1",
                source_thread_id="t1",
                match_type="message_embedding",
                retrieval_method="message_embedding",
                query_text="q",
                distance=0.12,
                rank=1,
            )
        ],
    )
    assert len(fused) == 1
    assert fused[0].match_type == "exact"
    assert "message_embedding" in fused[0].extra_methods


# ── T101: scoped embedding search ──────────────────────────────────────

def test_message_embedding_search_date_scoped(search_db) -> None:
    conn, logger, dataset_id, adapter = search_db
    full = search_message_embeddings(
        conn, logger, dataset_id=dataset_id, query="allergy",
        model_name="fake-search", adapter=adapter, top_k=10,
    )
    scope = MessageDateScope(start_timestamp="2024-01-10T00:00:00+00:00")
    scoped = search_message_embeddings(
        conn, logger, dataset_id=dataset_id, query="allergy",
        model_name="fake-search", adapter=adapter, top_k=10,
        date_scope=scope,
    )
    assert len(scoped) <= len(full)
    for hit in scoped:
        row = conn.execute(
            "SELECT timestamp FROM message WHERE dataset_id = ? AND message_id = ?",
            (dataset_id, hit.message_id),
        ).fetchone()
        assert row is not None
        assert row["timestamp"] >= scope.start_timestamp


def test_message_embedding_search_no_scope_same_as_full(search_db) -> None:
    conn, logger, dataset_id, adapter = search_db
    full = search_message_embeddings(
        conn, logger, dataset_id=dataset_id, query="allergy",
        model_name="fake-search", adapter=adapter, top_k=10,
    )
    none_scope = search_message_embeddings(
        conn, logger, dataset_id=dataset_id, query="allergy",
        model_name="fake-search", adapter=adapter, top_k=10,
        date_scope=None,
    )
    inactive = search_message_embeddings(
        conn, logger, dataset_id=dataset_id, query="allergy",
        model_name="fake-search", adapter=adapter, top_k=10,
        date_scope=MessageDateScope(),
    )
    assert len(none_scope) == len(full)
    assert len(inactive) == len(full)


def test_message_embedding_search_empty_range(search_db) -> None:
    conn, logger, dataset_id, adapter = search_db
    scope = MessageDateScope(
        start_timestamp="2020-01-01T00:00:00+00:00",
        end_timestamp="2020-01-02T00:00:00+00:00",
    )
    scoped = search_message_embeddings(
        conn, logger, dataset_id=dataset_id, query="allergy",
        model_name="fake-search", adapter=adapter, top_k=10,
        date_scope=scope,
    )
    assert scoped == []

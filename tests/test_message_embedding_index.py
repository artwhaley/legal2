"""Message embedding index tests."""

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.embeddings.adapters import FakeEmbeddingAdapter
from message_evidence_workstation.embeddings.index_jobs import build_message_embedding_index, get_ready_index
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def index_db(tmp_path):
    conn = connect(tmp_path / "msg_index.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_message_index_build_with_fake_adapter(index_db) -> None:
    conn, logger, dataset_id = index_db
    adapter = FakeEmbeddingAdapter(model_name="fake-msg", dimensions=8)
    info = adapter.load()
    result = build_message_embedding_index(
        conn,
        logger,
        dataset_id=dataset_id,
        adapter=adapter,
        adapter_info=info,
    )
    assert result.success, result.error
    assert result.count == 5
    row = get_ready_index(conn, dataset_id, "message", "fake-msg")
    assert row is not None
    assert row["status"] == "ready"
    stored = conn.execute(
        "SELECT COUNT(*) FROM message_embedding_vec WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchone()[0]
    assert stored == 5

"""FTS pagination hydration tests."""

from pathlib import Path
from unittest.mock import patch

import pytest

from message_evidence_workstation.db import repositories
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search import fts

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def fts_db(tmp_path):
    conn = connect(tmp_path / "pagination_hydration.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_fts_page_hydrates_with_single_batch_fetch(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    page = fts.search_messages(conn, logger, dataset_id, "the", limit=5, offset=0)
    calls: list[int] = []

    with patch(
        "message_evidence_workstation.db.repositories.fetch_messages_by_ids",
        side_effect=lambda _conn, _dataset_id, message_ids: calls.append(len(message_ids)) or {},
    ):
        repositories.fetch_messages_by_ids(
            conn,
            dataset_id,
            [hit.message_id for hit in page["hits"]],
        )

    assert len(page["hits"]) <= 5
    assert calls == [len(page["hits"])]

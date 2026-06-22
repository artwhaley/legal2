"""FTS5 search tests."""

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search import fts

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def fts_db(tmp_path):
    conn = connect(tmp_path / "fts.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_exact_search_finds_phrase(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    hits = fts.search_exact(conn, logger, dataset_id, "allergy form")
    assert [hit.message_id for hit in hits] == ["msg_001"]


def test_partial_search_finds_prefix(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    hits = fts.search_partial(conn, logger, dataset_id, "aller")
    assert "msg_001" in [hit.message_id for hit in hits]


def test_empty_query_returns_no_hits(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    assert fts.search_exact(conn, logger, dataset_id, "   ") == []


def test_multi_token_search_matches_any_token(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    results = fts.search_messages(conn, logger, dataset_id, "allergies allergic allergy")
    message_ids = {hit.message_id for hit in results["exact"] + results["partial"]}
    assert "msg_001" in message_ids


def test_allergies_finds_allergy(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    results = fts.search_messages(conn, logger, dataset_id, "allergies")
    message_ids = {hit.message_id for hit in results["exact"] + results["partial"]}
    assert "msg_001" in message_ids


def test_malformed_partial_query_returns_empty(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    hits = fts.search_partial(conn, logger, dataset_id, "NEAR(")
    assert hits == []


def test_question_mark_in_query_does_not_raise(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    results = fts.search_messages(conn, logger, dataset_id, "allergies?")
    message_ids = {hit.message_id for hit in results["exact"] + results["partial"]}
    assert "msg_001" in message_ids

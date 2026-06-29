"""Repository tests for categories."""

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.repositories import create_category, list_categories
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from pathlib import Path


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def repo_db(tmp_path):
    conn = connect(tmp_path / "test.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_category_crud(repo_db) -> None:
    conn, logger, dataset_id = repo_db
    school = create_category(conn, logger, dataset_id, "school")
    work = create_category(conn, logger, dataset_id, "work")
    categories = list_categories(conn, dataset_id)
    assert {category.name for category in categories} == {"school", "work"}
    assert school.category_id != work.category_id

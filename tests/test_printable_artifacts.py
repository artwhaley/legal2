"""Printable artifact schema and repository tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from message_evidence_workstation.db import evidence_blocks, printable_artifacts
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import get_schema_version, initialize_schema
from message_evidence_workstation.domain.constants import SCHEMA_VERSION
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def workspace(tmp_path):
    conn = connect(tmp_path / "printable.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    yield conn, logger, dataset_id
    conn.close()


def _create_block(conn, logger, dataset_id: int, title: str = "Block one") -> int:
    category = evidence_blocks.ensure_uncategorized_category(conn, logger, dataset_id)
    messages = __import__(
        "message_evidence_workstation.db.repositories",
        fromlist=["list_messages_for_thread"],
    ).list_messages_for_thread(conn, dataset_id, "thread_001")
    block = evidence_blocks.create_evidence_block(
        conn,
        logger,
        dataset_id=dataset_id,
        category_id=category.category_id,
        source_thread_id="thread_001",
        title=title,
        core_hit_message_id="msg_001",
        ordered_message_ids=[message.message_id for message in messages],
    )
    return block.evidence_block_id


def test_migration_adds_printable_tables(workspace) -> None:
    conn, _logger, _dataset_id = workspace
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    assert "printable_artifact_group" in tables
    assert "printable_artifact" in tables
    assert "printable_artifact_evidence_block" in tables
    assert get_schema_version(conn) == SCHEMA_VERSION


def test_ensure_default_group(workspace) -> None:
    conn, logger, dataset_id = workspace
    group = printable_artifacts.ensure_default_printable_artifact_group(conn, logger, dataset_id)
    again = printable_artifacts.ensure_default_printable_artifact_group(conn, logger, dataset_id)
    assert group.printable_artifact_group_id == again.printable_artifact_group_id


def test_create_artifact_from_block_and_append(workspace) -> None:
    conn, logger, dataset_id = workspace
    group = printable_artifacts.ensure_default_printable_artifact_group(conn, logger, dataset_id)
    block_a = _create_block(conn, logger, dataset_id, "Alpha")
    block_b = _create_block(conn, logger, dataset_id, "Beta")
    artifact = printable_artifacts.create_printable_artifact_from_evidence_block(
        conn,
        logger,
        dataset_id,
        group.printable_artifact_group_id,
        block_a,
    )
    assert artifact.title == "Alpha"
    printable_artifacts.append_evidence_block_to_printable_artifact(
        conn,
        logger,
        artifact.printable_artifact_id,
        block_b,
    )
    context = printable_artifacts.load_printable_artifact_context(conn, artifact.printable_artifact_id)
    assert context is not None
    assert [block.evidence_block.title for block in context.blocks] == ["Alpha", "Beta"]


def test_same_block_twice_in_one_artifact(workspace) -> None:
    conn, logger, dataset_id = workspace
    group = printable_artifacts.ensure_default_printable_artifact_group(conn, logger, dataset_id)
    block_id = _create_block(conn, logger, dataset_id)
    artifact = printable_artifacts.create_printable_artifact_from_evidence_block(
        conn,
        logger,
        dataset_id,
        group.printable_artifact_group_id,
        block_id,
    )
    printable_artifacts.append_evidence_block_to_printable_artifact(
        conn,
        logger,
        artifact.printable_artifact_id,
        block_id,
    )
    context = printable_artifacts.load_printable_artifact_context(conn, artifact.printable_artifact_id)
    assert context is not None
    assert len(context.blocks) == 2
    assert context.blocks[0].block_label == "A"
    assert context.blocks[1].block_label == "B"


def test_same_block_in_multiple_artifacts(workspace) -> None:
    conn, logger, dataset_id = workspace
    group = printable_artifacts.ensure_default_printable_artifact_group(conn, logger, dataset_id)
    block_id = _create_block(conn, logger, dataset_id)
    first = printable_artifacts.create_printable_artifact_from_evidence_block(
        conn,
        logger,
        dataset_id,
        group.printable_artifact_group_id,
        block_id,
    )
    second = printable_artifacts.create_printable_artifact_from_evidence_block(
        conn,
        logger,
        dataset_id,
        group.printable_artifact_group_id,
        block_id,
    )
    assert first.printable_artifact_id != second.printable_artifact_id


def test_reorder_remove_and_move_group(workspace) -> None:
    conn, logger, dataset_id = workspace
    default_group = printable_artifacts.ensure_default_printable_artifact_group(conn, logger, dataset_id)
    other_group = printable_artifacts.create_printable_artifact_group(conn, logger, dataset_id, "Exhibits")
    block_a = _create_block(conn, logger, dataset_id, "One")
    block_b = _create_block(conn, logger, dataset_id, "Two")
    artifact = printable_artifacts.create_printable_artifact_from_evidence_block(
        conn,
        logger,
        dataset_id,
        default_group.printable_artifact_group_id,
        block_a,
    )
    join_b = printable_artifacts.append_evidence_block_to_printable_artifact(
        conn,
        logger,
        artifact.printable_artifact_id,
        block_b,
    )
    context = printable_artifacts.load_printable_artifact_context(conn, artifact.printable_artifact_id)
    assert context is not None
    join_a = context.blocks[0].join.printable_artifact_evidence_block_id
    printable_artifacts.reorder_printable_artifact_blocks(
        conn,
        logger,
        artifact.printable_artifact_id,
        [join_b.printable_artifact_evidence_block_id, join_a],
    )
    reloaded = printable_artifacts.load_printable_artifact_context(conn, artifact.printable_artifact_id)
    assert reloaded is not None
    assert [block.evidence_block.title for block in reloaded.blocks] == ["Two", "One"]

    printable_artifacts.remove_printable_artifact_block(
        conn,
        logger,
        join_b.printable_artifact_evidence_block_id,
    )
    assert evidence_blocks.get_evidence_block(conn, block_b) is not None

    printable_artifacts.move_printable_artifact_to_group(
        conn,
        logger,
        artifact.printable_artifact_id,
        other_group.printable_artifact_group_id,
    )
    moved = printable_artifacts.list_printable_artifacts(conn, other_group.printable_artifact_group_id)
    assert any(row.printable_artifact_id == artifact.printable_artifact_id for row in moved)


def test_metadata_save_reload(workspace) -> None:
    conn, logger, dataset_id = workspace
    group = printable_artifacts.ensure_default_printable_artifact_group(conn, logger, dataset_id)
    block_id = _create_block(conn, logger, dataset_id)
    artifact = printable_artifacts.create_printable_artifact_from_evidence_block(
        conn,
        logger,
        dataset_id,
        group.printable_artifact_group_id,
        block_id,
    )
    printable_artifacts.update_printable_artifact_metadata(
        conn,
        logger,
        artifact.printable_artifact_id,
        "Exhibit title",
        "E-12",
        "CV-2024-001",
    )
    context = printable_artifacts.load_printable_artifact_context(conn, artifact.printable_artifact_id)
    assert context is not None
    assert context.artifact.title == "Exhibit title"
    assert context.artifact.exhibit_number == "E-12"
    assert context.artifact.case_number == "CV-2024-001"


def test_dataset_reload_clears_printable_artifacts(workspace) -> None:
    conn, logger, dataset_id = workspace
    group = printable_artifacts.ensure_default_printable_artifact_group(conn, logger, dataset_id)
    block_id = _create_block(conn, logger, dataset_id)
    printable_artifacts.create_printable_artifact_from_evidence_block(
        conn,
        logger,
        dataset_id,
        group.printable_artifact_group_id,
        block_id,
    )

    load_normalized_dataset(conn, logger, FIXTURE_DIR, reload=True)

    assert conn.execute("SELECT COUNT(*) FROM printable_artifact_evidence_block").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM printable_artifact").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM printable_artifact_group").fetchone()[0] == 0

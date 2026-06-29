"""Printable preview and provenance model tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication

from message_evidence_workstation.db import evidence_blocks, printable_artifacts
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.domain.models import (
    EvidenceBlock,
    Message,
    PrintableArtifact,
    PrintableArtifactBlockContext,
    PrintableArtifactEvidenceBlock,
    SourceThread,
)
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.output.block_labels import block_label_for_index
from message_evidence_workstation.output.printable_preview import (
    build_block_provenance,
    build_print_layout,
    build_printable_preview,
    format_block_provenance,
)
from message_evidence_workstation.output.print_layout import (
    StubLayoutMetrics,
    TightPageMetrics,
    build_print_layout as layout_build,
)
from message_evidence_workstation.output.print_layout_render import export_layout_to_pdf
from message_evidence_workstation.ui.printable_preview_widget import PrintPreviewWidget

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_block_label_helper() -> None:
    assert block_label_for_index(0) == "A"
    assert block_label_for_index(1) == "B"
    assert block_label_for_index(25) == "Z"
    assert block_label_for_index(26) == "AA"


def _sample_context(tmp_path):
    conn = connect(tmp_path / "preview.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    category = evidence_blocks.ensure_uncategorized_category(conn, logger, dataset_id)
    from message_evidence_workstation.db import repositories

    messages = repositories.list_messages_for_thread(conn, dataset_id, "thread_001")[:3]
    block = evidence_blocks.create_evidence_block(
        conn,
        logger,
        dataset_id=dataset_id,
        category_id=category.category_id,
        source_thread_id="thread_001",
        title="Allergy form",
        core_hit_message_id=messages[0].message_id,
        ordered_message_ids=[message.message_id for message in messages],
        context_start_slot=0,
        relevant_start_slot=0,
        relevant_end_slot=2,
        context_end_slot=3,
    )
    group = printable_artifacts.ensure_default_printable_artifact_group(conn, logger, dataset_id)
    artifact = printable_artifacts.create_printable_artifact_from_evidence_block(
        conn,
        logger,
        dataset_id,
        group.printable_artifact_group_id,
        block.evidence_block_id,
    )
    printable_artifacts.update_printable_artifact_metadata(
        conn,
        logger,
        artifact.printable_artifact_id,
        "School allergy exhibit",
        "E-1",
        "CASE-42",
    )
    context = printable_artifacts.load_printable_artifact_context(conn, artifact.printable_artifact_id)
    conn.close()
    return context


def test_preview_one_page_artifact(tmp_path) -> None:
    context = _sample_context(tmp_path)
    assert context is not None
    preview = build_printable_preview(context)
    assert preview.title == "School allergy exhibit"
    assert len(preview.pages) >= 1
    assert preview.block_sections[0].messages


def test_preview_multi_block_order(tmp_path) -> None:
    conn = connect(tmp_path / "multi.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    category = evidence_blocks.ensure_uncategorized_category(conn, logger, dataset_id)
    from message_evidence_workstation.db import repositories

    messages = repositories.list_messages_for_thread(conn, dataset_id, "thread_001")
    ordered_ids = [message.message_id for message in messages]
    block_a = evidence_blocks.create_evidence_block(
        conn,
        logger,
        dataset_id=dataset_id,
        category_id=category.category_id,
        source_thread_id="thread_001",
        title="First",
        core_hit_message_id=ordered_ids[0],
        ordered_message_ids=ordered_ids,
        context_start_slot=0,
        relevant_start_slot=0,
        relevant_end_slot=1,
        context_end_slot=2,
    )
    block_b = evidence_blocks.create_evidence_block(
        conn,
        logger,
        dataset_id=dataset_id,
        category_id=category.category_id,
        source_thread_id="thread_001",
        title="Second",
        core_hit_message_id=ordered_ids[2],
        ordered_message_ids=ordered_ids,
        context_start_slot=2,
        relevant_start_slot=2,
        relevant_end_slot=3,
        context_end_slot=4,
    )
    group = printable_artifacts.ensure_default_printable_artifact_group(conn, logger, dataset_id)
    artifact = printable_artifacts.create_printable_artifact_from_evidence_block(
        conn,
        logger,
        dataset_id,
        group.printable_artifact_group_id,
        block_a.evidence_block_id,
    )
    printable_artifacts.append_evidence_block_to_printable_artifact(
        conn,
        logger,
        artifact.printable_artifact_id,
        block_b.evidence_block_id,
    )
    context = printable_artifacts.load_printable_artifact_context(conn, artifact.printable_artifact_id)
    preview = build_printable_preview(context)
    assert [section.label for section in preview.block_sections] == ["A", "B"]
    assert [section.title for section in preview.block_sections] == ["First", "Second"]
    conn.close()


def test_preview_includes_sender_timestamp_and_footer(tmp_path) -> None:
    context = _sample_context(tmp_path)
    assert context is not None
    preview = build_print_layout(context)
    message = preview.block_sections[0].messages[0]
    assert message.sender
    assert message.timestamp
    page = preview.pages[0]
    assert preview.footer_exhibit == "E-1"
    assert preview.footer_case == "CASE-42"
    assert page.page_number == 1
    assert page.title == "School allergy exhibit"
    assert page.footer_exhibit == "E-1"
    assert page.footer_case == "CASE-42"
    assert page.total_pages == len(preview.pages)
    assert len(preview.pages) >= 1


def test_provenance_minimal_metadata(tmp_path) -> None:
    context = _sample_context(tmp_path)
    assert context is not None
    block_context = context.blocks[0]
    provenance = build_block_provenance(block_context)
    text = format_block_provenance("A", provenance)
    assert "Block A:" in text
    assert "source_thread_id=thread_001" in text
    assert "message_ids=" in text


def test_provenance_enriched_metadata() -> None:
    message = Message(
        message_id="msg_001",
        dataset_id=1,
        source_thread_id="thread_001",
        source_platform="facebook",
        source_message_id="fb-99",
        timestamp="2024-01-01T10:00:00+00:00",
        sender_id="a",
        sender_display="Alice",
        body="hello",
        body_normalized="hello",
        has_attachment=False,
        attachment_summary="",
        sort_index=0,
        source_metadata_json={
            "source_file_name": "dump.json",
            "source_file_hash": "abc123",
            "import_timestamp": "2024-01-02T00:00:00+00:00",
        },
    )
    block = EvidenceBlock(
        evidence_block_id=1,
        dataset_id=1,
        category_id=1,
        source_thread_id="thread_001",
        title="t",
        summary="",
        core_hit_message_id="msg_001",
        context_start_slot=0,
        relevant_start_slot=0,
        relevant_end_slot=1,
        context_end_slot=1,
        highlighted_message_ids=frozenset(),
        created_by="manual",
        created_at="t",
        updated_at="t",
    )
    thread = SourceThread(
        source_thread_id="thread_001",
        dataset_id=1,
        source_platform="facebook",
        platform_thread_id="plat-1",
        display_title="Thread",
        participant_summary="",
        start_ts="t",
        end_ts="t",
        message_count=1,
        metadata_json={"import_file": "archive.zip"},
    )
    context_block = PrintableArtifactBlockContext(
        join=PrintableArtifactEvidenceBlock(1, 1, 1, 0, "t"),
        evidence_block=block,
        block_label="A",
        messages=[message],
        source_thread=thread,
        dataset_name="Sample",
    )
    text = format_block_provenance("A", build_block_provenance(context_block))
    assert "source_file_name=dump.json" in text
    assert "source_file_hash=abc123" in text
    assert "thread.import_file=archive.zip" in text
    assert "platform_thread_id=plat-1" in text


def test_duplicate_blocks_produce_two_ledger_entries() -> None:
    message = Message(
        message_id="msg_001",
        dataset_id=1,
        source_thread_id="thread_001",
        source_platform="facebook",
        source_message_id="fb-1",
        timestamp="t",
        sender_id="a",
        sender_display="A",
        body="hi",
        body_normalized="hi",
        has_attachment=False,
        attachment_summary="",
        sort_index=0,
        source_metadata_json={},
    )
    block = EvidenceBlock(
        evidence_block_id=1,
        dataset_id=1,
        category_id=1,
        source_thread_id="thread_001",
        title="dup",
        summary="",
        core_hit_message_id="msg_001",
        context_start_slot=0,
        relevant_start_slot=0,
        relevant_end_slot=1,
        context_end_slot=1,
        highlighted_message_ids=frozenset(),
        created_by="manual",
        created_at="t",
        updated_at="t",
    )
    join_a = PrintableArtifactEvidenceBlock(1, 1, 1, 0, "t")
    join_b = PrintableArtifactEvidenceBlock(2, 1, 1, 1, "t")
    artifact = PrintableArtifact(1, 1, 1, "t", "", "", 0, "t", "t")
    from message_evidence_workstation.domain.models import PrintableArtifactContext

    context = PrintableArtifactContext(
        artifact=artifact,
        group_name="g",
        dataset_name="d",
        blocks=[
            PrintableArtifactBlockContext(
                join=join_a,
                evidence_block=block,
                block_label="A",
                messages=[message],
                source_thread=None,
                dataset_name="d",
            ),
            PrintableArtifactBlockContext(
                join=join_b,
                evidence_block=block,
                block_label="B",
                messages=[message],
                source_thread=None,
                dataset_name="d",
            ),
        ],
    )
    preview = build_print_layout(context)
    assert len(preview.provenance_entries) == 2
    assert preview.provenance_entries[0].label == "A"
    assert preview.provenance_entries[1].label == "B"


def _long_body_context(body: str):
    from message_evidence_workstation.domain.models import PrintableArtifactContext

    message = Message(
        message_id="msg_001",
        dataset_id=1,
        source_thread_id="thread_001",
        source_platform="facebook",
        source_message_id="fb-1",
        timestamp="t",
        sender_id="a",
        sender_display="Alice",
        body=body,
        body_normalized=body,
        has_attachment=False,
        attachment_summary="",
        sort_index=0,
        source_metadata_json={},
    )
    block = EvidenceBlock(
        evidence_block_id=1,
        dataset_id=1,
        category_id=1,
        source_thread_id="thread_001",
        title="Long block",
        summary="",
        core_hit_message_id="msg_001",
        context_start_slot=0,
        relevant_start_slot=0,
        relevant_end_slot=1,
        context_end_slot=1,
        highlighted_message_ids=frozenset(),
        created_by="manual",
        created_at="t",
        updated_at="t",
    )
    artifact = PrintableArtifact(1, 1, 1, "Exhibit", "E-9", "CASE-9", 0, "t", "t")
    return PrintableArtifactContext(
        artifact=artifact,
        group_name="g",
        dataset_name="d",
        blocks=[
            PrintableArtifactBlockContext(
                join=PrintableArtifactEvidenceBlock(1, 1, 1, 0, "t"),
                evidence_block=block,
                block_label="A",
                messages=[message],
                source_thread=None,
                dataset_name="d",
            )
        ],
    )


def test_layout_title_and_footer_on_every_page() -> None:
    metrics = TightPageMetrics()
    body = " ".join(["word"] * 400)
    document = layout_build(_long_body_context(body), metrics=metrics)
    assert len(document.pages) > 1
    for page in document.pages:
        assert page.title == "Exhibit"
        assert page.footer_exhibit == "E-9"
        assert page.footer_case == "CASE-9"
        assert page.total_pages == len(document.pages)


def test_layout_provenance_only_at_end() -> None:
    metrics = TightPageMetrics()
    body = " ".join(["word"] * 400)
    document = layout_build(_long_body_context(body), metrics=metrics)
    provenance_pages = [
        index
        for index, page in enumerate(document.pages)
        if any(item.kind.startswith("provenance") for item in page.items)
    ]
    assert provenance_pages
    assert provenance_pages == list(range(provenance_pages[0], len(document.pages)))


def test_layout_block_header_format() -> None:
    metrics = StubLayoutMetrics()
    document = layout_build(_long_body_context("short"), metrics=metrics)
    headers = [item for item in document.pages[0].items if item.kind == "block_header"]
    subtitles = [item for item in document.pages[0].items if item.kind == "block_subtitle"]
    assert headers
    assert headers[0].text == "Block A"
    assert subtitles
    assert subtitles[0].text == "Long block"


def test_layout_multi_block_breaks_at_wrap_boundaries() -> None:
    message = Message(
        message_id="msg_001",
        dataset_id=1,
        source_thread_id="thread_001",
        source_platform="facebook",
        source_message_id="fb-1",
        timestamp="t",
        sender_id="a",
        sender_display="A",
        body="alpha beta gamma delta",
        body_normalized="alpha beta gamma delta",
        has_attachment=False,
        attachment_summary="",
        sort_index=0,
        source_metadata_json={},
    )
    block_a = EvidenceBlock(
        evidence_block_id=1,
        dataset_id=1,
        category_id=1,
        source_thread_id="thread_001",
        title="First",
        summary="",
        core_hit_message_id="msg_001",
        context_start_slot=0,
        relevant_start_slot=0,
        relevant_end_slot=1,
        context_end_slot=1,
        highlighted_message_ids=frozenset(),
        created_by="manual",
        created_at="t",
        updated_at="t",
    )
    block_b = EvidenceBlock(
        evidence_block_id=2,
        dataset_id=1,
        category_id=1,
        source_thread_id="thread_001",
        title="Second",
        summary="",
        core_hit_message_id="msg_001",
        context_start_slot=0,
        relevant_start_slot=0,
        relevant_end_slot=1,
        context_end_slot=1,
        highlighted_message_ids=frozenset(),
        created_by="manual",
        created_at="t",
        updated_at="t",
    )
    from message_evidence_workstation.domain.models import PrintableArtifactContext

    artifact = PrintableArtifact(1, 1, 1, "Multi", "", "", 0, "t", "t")
    context = PrintableArtifactContext(
        artifact=artifact,
        group_name="g",
        dataset_name="d",
        blocks=[
            PrintableArtifactBlockContext(
                join=PrintableArtifactEvidenceBlock(1, 1, 1, 0, "t"),
                evidence_block=block_a,
                block_label="A",
                messages=[message],
                source_thread=None,
                dataset_name="d",
            ),
            PrintableArtifactBlockContext(
                join=PrintableArtifactEvidenceBlock(2, 1, 2, 1, "t"),
                evidence_block=block_b,
                block_label="B",
                messages=[message],
                source_thread=None,
                dataset_name="d",
            ),
        ],
    )
    small_page_metrics = StubLayoutMetrics(
        content_width_pt=60.0,
        roles={
            role: metrics
            for role, metrics in StubLayoutMetrics()._roles.items()
        },
    )
    document = layout_build(context, metrics=small_page_metrics)
    all_headers = [
        item.text
        for page in document.pages
        for item in page.items
        if item.kind == "block_header"
    ]
    all_subtitles = [
        item.text
        for page in document.pages
        for item in page.items
        if item.kind == "block_subtitle"
    ]
    assert "Block A" in all_headers
    assert "Block B" in all_headers
    assert "First" in all_subtitles
    assert "Second" in all_subtitles
    message_blocks = [
        item
        for page in document.pages
        for item in page.items
        if item.kind == "message_block"
    ]
    assert message_blocks
    assert all(item.body_lines for item in message_blocks)


def test_layout_fixture_page_count(tmp_path) -> None:
    context = _sample_context(tmp_path)
    metrics = StubLayoutMetrics()
    document = layout_build(context, metrics=metrics)
    assert len(document.pages) >= 1
    provenance_kinds = {
        item.kind
        for page in document.pages
        for item in page.items
        if item.kind.startswith("provenance")
    }
    assert "provenance_header" in provenance_kinds
    assert "provenance_entry" in provenance_kinds


def test_layout_title_falls_back_to_block_summary() -> None:
    context = _long_body_context("brief body")
    context.artifact.title = ""
    context.blocks[0].evidence_block.summary = (
        "Discussion about the school allergy form and where the epi pen was kept for Mia."
    )
    document = layout_build(context, metrics=StubLayoutMetrics())
    assert document.title == "Discussion about the school allergy form and where the epi pen was kept for Mia."


def test_layout_message_block_carries_indent_and_timestamp() -> None:
    document = layout_build(_long_body_context("alpha beta gamma delta"), metrics=StubLayoutMetrics())
    message_blocks = [item for item in document.pages[0].items if item.kind == "message_block"]
    assert message_blocks
    assert message_blocks[0].body_indent_pt > 0
    assert message_blocks[0].timestamp == "t"


def test_layout_marks_context_and_highlighted_messages() -> None:
    from message_evidence_workstation.domain.models import PrintableArtifactContext

    messages = [
        Message(
            message_id=f"msg_{index}",
            dataset_id=1,
            source_thread_id="thread_001",
            source_platform="facebook",
            source_message_id=f"fb-{index}",
            timestamp=f"t{index}",
            sender_id="a",
            sender_display="Alice",
            body=f"message {index}",
            body_normalized=f"message {index}",
            has_attachment=False,
            attachment_summary="",
            sort_index=index,
            source_metadata_json={},
        )
        for index in range(4)
    ]
    block = EvidenceBlock(
        evidence_block_id=1,
        dataset_id=1,
        category_id=1,
        source_thread_id="thread_001",
        title="Medical references",
        summary="",
        core_hit_message_id="msg_1",
        context_start_slot=10,
        relevant_start_slot=11,
        relevant_end_slot=13,
        context_end_slot=14,
        highlighted_message_ids=frozenset({"msg_2"}),
        created_by="manual",
        created_at="t",
        updated_at="t",
    )
    artifact = PrintableArtifact(1, 1, 1, "Exhibit", "", "", 0, "t", "t")
    context = PrintableArtifactContext(
        artifact=artifact,
        group_name="g",
        dataset_name="d",
        blocks=[
            PrintableArtifactBlockContext(
                join=PrintableArtifactEvidenceBlock(1, 1, 1, 0, "t"),
                evidence_block=block,
                block_label="A",
                messages=messages,
                source_thread=None,
                dataset_name="d",
            )
        ],
    )
    document = layout_build(context, metrics=StubLayoutMetrics())
    message_blocks = [item for item in document.pages[0].items if item.kind == "message_block"]
    assert len(message_blocks) == 4
    assert message_blocks[0].is_context is True
    assert message_blocks[1].is_context is False
    assert message_blocks[2].is_context is False
    assert message_blocks[3].is_context is True
    assert message_blocks[2].is_highlighted is True
    assert message_blocks[1].is_highlighted is False


def test_pdf_export_page_count(qapp, tmp_path) -> None:
    body = " ".join(["word"] * 400)
    document = layout_build(_long_body_context(body), metrics=TightPageMetrics())
    pdf_path = tmp_path / "preview.pdf"
    export_layout_to_pdf(document, pdf_path)
    pdf = QPdfDocument()
    pdf.load(str(pdf_path))
    assert pdf.pageCount() == len(document.pages)


def test_print_preview_widget_smoke(qapp, tmp_path) -> None:
    context = _sample_context(tmp_path)
    document = build_print_layout(context)
    widget = PrintPreviewWidget()
    widget.set_layout_document(document)
    qapp.processEvents()
    assert widget.next_button.isEnabled() is (len(document.pages) > 1)
    assert not widget.prev_button.isEnabled()
    assert widget.page_label.text() == f"1 / {len(document.pages)}"
    if len(document.pages) > 1:
        widget.show_next_page()
        qapp.processEvents()
        assert widget.prev_button.isEnabled()
        assert widget.page_label.text() == f"2 / {len(document.pages)}"

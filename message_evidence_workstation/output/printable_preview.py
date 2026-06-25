"""Printable artifact preview model — layout, pagination, and provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from message_evidence_workstation.domain.models import PrintableArtifactBlockContext, PrintableArtifactContext
from message_evidence_workstation.output.block_labels import block_label_for_index

LINES_PER_PAGE = 32
WRAP_WIDTH = 72


@dataclass(slots=True)
class PrintableBlockProvenance:
    """Collected provenance fields for one artifact block instance."""

    entries: list[tuple[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class PreviewMessageEntry:
    sender: str
    timestamp: str
    body: str


@dataclass(slots=True)
class PreviewBlockSection:
    label: str
    title: str
    messages: list[PreviewMessageEntry]


@dataclass(slots=True)
class PreviewProvenanceEntry:
    label: str
    text: str


@dataclass(slots=True)
class PreviewContentLine:
    kind: str
    text: str


@dataclass(slots=True)
class PrintablePreviewPage:
    page_number: int
    lines: list[PreviewContentLine]


@dataclass(slots=True)
class PrintablePreviewModel:
    title: str
    exhibit_number: str
    case_number: str
    block_sections: list[PreviewBlockSection]
    provenance_entries: list[PreviewProvenanceEntry]
    pages: list[PrintablePreviewPage]
    footer_exhibit: str
    footer_case: str


def _wrap_text(text: str, width: int = WRAP_WIDTH) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _stringify_metadata_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _append_if_present(
    entries: list[tuple[str, str]],
    label: str,
    value: Any,
) -> None:
    rendered = _stringify_metadata_value(value)
    if rendered is not None:
        entries.append((label, rendered))


def _metadata_pairs(metadata: dict[str, Any], keys: tuple[str, ...]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key in keys:
        if key in metadata:
            rendered = _stringify_metadata_value(metadata[key])
            if rendered is not None:
                pairs.append((key, rendered))
    return pairs


def build_block_provenance(context_block: PrintableArtifactBlockContext) -> PrintableBlockProvenance:
    entries: list[tuple[str, str]] = []
    block = context_block.evidence_block
    thread = context_block.source_thread
    messages = context_block.messages

    message_ids = [message.message_id for message in messages]
    if message_ids:
        _append_if_present(entries, "message_ids", ", ".join(message_ids))

    source_message_ids = [message.source_message_id for message in messages if message.source_message_id]
    if source_message_ids:
        _append_if_present(entries, "source_message_ids", ", ".join(dict.fromkeys(source_message_ids)))

    _append_if_present(entries, "source_thread_id", block.source_thread_id)

    if thread is not None:
        _append_if_present(entries, "platform_thread_id", thread.platform_thread_id)
        _append_if_present(entries, "source_platform", thread.source_platform)
        for key, value in _metadata_pairs(
            thread.metadata_json,
            ("import_batch_id", "import_file", "source_file", "dump_path"),
        ):
            entries.append((f"thread.{key}", value))

    if messages:
        timestamps = [message.timestamp for message in messages if message.timestamp]
        if timestamps:
            _append_if_present(
                entries,
                "message_timestamp_range",
                f"{timestamps[0]} … {timestamps[-1]}",
            )
        senders = sorted({message.sender_display or message.sender_id for message in messages})
        if senders:
            _append_if_present(entries, "senders", ", ".join(senders))

    for message in messages:
        for key in ("source_file", "source_file_path", "source_file_name", "source_file_hash"):
            if key in message.source_metadata_json:
                rendered = _stringify_metadata_value(message.source_metadata_json[key])
                if rendered is not None:
                    entries.append((key, rendered))
        for key, value in _metadata_pairs(
            message.source_metadata_json,
            ("import_batch_id", "import_timestamp", "dump_file", "archive_path"),
        ):
            entries.append((key, value))

    _append_if_present(entries, "dataset_id", str(block.dataset_id))
    if context_block.dataset_name:
        _append_if_present(entries, "dataset_name", context_block.dataset_name)

    # TODO: import_batch / source_file tables when donor import schema adds them.

    return PrintableBlockProvenance(entries=entries)


def format_block_provenance(label: str, provenance: PrintableBlockProvenance) -> str:
    if not provenance.entries:
        return f"Block {label}:"
    parts = [f"{name}={value}" for name, value in provenance.entries]
    return f"Block {label}: " + "; ".join(parts)


def _build_content_lines(context: PrintableArtifactContext) -> list[PreviewContentLine]:
    lines: list[PreviewContentLine] = []
    title = context.artifact.title.strip() or "Untitled exhibit"
    lines.append(PreviewContentLine(kind="title", text=title))
    lines.append(PreviewContentLine(kind="blank", text=""))

    for block_context in context.blocks:
        label = block_context.block_label
        lines.append(PreviewContentLine(kind="block_label", text=f"Block {label}"))
        block_title = block_context.evidence_block.title.strip()
        if block_title:
            lines.append(PreviewContentLine(kind="block_title", text=block_title))
        for message in block_context.messages:
            meta = f"{message.sender_display or message.sender_id} · {message.timestamp}"
            lines.append(PreviewContentLine(kind="message_meta", text=meta))
            for wrapped in _wrap_text(message.body):
                lines.append(PreviewContentLine(kind="message_body", text=wrapped))
            lines.append(PreviewContentLine(kind="blank", text=""))

    if context.blocks:
        lines.append(PreviewContentLine(kind="provenance_header", text="Provenance"))
        for block_context in context.blocks:
            provenance = build_block_provenance(block_context)
            ledger_line = format_block_provenance(block_context.block_label, provenance)
            for wrapped in _wrap_text(ledger_line, width=WRAP_WIDTH):
                lines.append(PreviewContentLine(kind="provenance_entry", text=wrapped))

    return lines


def _paginate_lines(content_lines: list[PreviewContentLine]) -> list[PrintablePreviewPage]:
    if not content_lines:
        return [PrintablePreviewPage(page_number=1, lines=[])]
    pages: list[PrintablePreviewPage] = []
    page_lines: list[PreviewContentLine] = []
    for line in content_lines:
        page_lines.append(line)
        if len(page_lines) >= LINES_PER_PAGE:
            pages.append(PrintablePreviewPage(page_number=len(pages) + 1, lines=page_lines))
            page_lines = []
    if page_lines:
        pages.append(PrintablePreviewPage(page_number=len(pages) + 1, lines=page_lines))
    return pages


def build_printable_preview(context: PrintableArtifactContext) -> PrintablePreviewModel:
    block_sections: list[PreviewBlockSection] = []
    for block_context in context.blocks:
        block_sections.append(
            PreviewBlockSection(
                label=block_context.block_label,
                title=block_context.evidence_block.title,
                messages=[
                    PreviewMessageEntry(
                        sender=message.sender_display or message.sender_id,
                        timestamp=message.timestamp,
                        body=message.body,
                    )
                    for message in block_context.messages
                ],
            )
        )
    provenance_entries = [
        PreviewProvenanceEntry(
            label=block_context.block_label,
            text=format_block_provenance(
                block_context.block_label,
                build_block_provenance(block_context),
            ),
        )
        for block_context in context.blocks
    ]
    content_lines = _build_content_lines(context)
    pages = _paginate_lines(content_lines)
    return PrintablePreviewModel(
        title=context.artifact.title.strip() or "Untitled exhibit",
        exhibit_number=context.artifact.exhibit_number,
        case_number=context.artifact.case_number,
        block_sections=block_sections,
        provenance_entries=provenance_entries,
        pages=pages,
        footer_exhibit=context.artifact.exhibit_number,
        footer_case=context.artifact.case_number,
    )


def refresh_block_labels(blocks: list[PrintableArtifactBlockContext]) -> None:
    for index, block in enumerate(blocks):
        block.block_label = block_label_for_index(index)

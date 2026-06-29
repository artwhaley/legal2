"""Printable artifact preview model — provenance helpers and layout entry point."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from message_evidence_workstation.domain.models import PrintableArtifactBlockContext, PrintableArtifactContext
from message_evidence_workstation.output.block_labels import block_label_for_index

__all__ = [
    "PrintableBlockProvenance",
    "PreviewMessageEntry",
    "PreviewBlockSection",
    "PreviewProvenanceEntry",
    "PrintLayoutDocument",
    "PrintLayoutPage",
    "PrintLayoutItem",
    "build_block_provenance",
    "format_block_provenance",
    "build_print_layout",
    "build_printable_preview",
    "refresh_block_labels",
]


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

    return PrintableBlockProvenance(entries=entries)


def format_block_provenance(label: str, provenance: PrintableBlockProvenance) -> str:
    if not provenance.entries:
        return f"Block {label}:"
    parts = [f"{name}={value}" for name, value in provenance.entries]
    return f"Block {label}: " + "; ".join(parts)


def build_print_layout(context: PrintableArtifactContext, metrics=None):
    from message_evidence_workstation.output.print_layout import build_print_layout as _build

    return _build(context, metrics=metrics)


def build_printable_preview(context: PrintableArtifactContext):
    return build_print_layout(context)


def refresh_block_labels(blocks: list[PrintableArtifactBlockContext]) -> None:
    for index, block in enumerate(blocks):
        block.block_label = block_label_for_index(index)


def __getattr__(name: str):
    if name in {"PrintLayoutDocument", "PrintLayoutPage", "PrintLayoutItem"}:
        from message_evidence_workstation.output import print_layout as module

        return getattr(module, name)
    raise AttributeError(name)

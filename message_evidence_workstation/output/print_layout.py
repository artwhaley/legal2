"""Measured print layout engine for printable artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from message_evidence_workstation.domain.models import EvidenceBlock, PrintableArtifactContext
from message_evidence_workstation.output.printable_preview import (
    PreviewBlockSection,
    PreviewMessageEntry,
    PreviewProvenanceEntry,
    build_block_provenance,
    format_block_provenance,
)

POINTS_PER_INCH = 72.0

PAGE_WIDTH_IN = 8.5
PAGE_HEIGHT_IN = 11.0
MARGIN_TOP_IN = 0.9
MARGIN_BOTTOM_IN = 0.85
MARGIN_LEFT_IN = 0.85
MARGIN_RIGHT_IN = 0.85

PAGE_WIDTH_PT = PAGE_WIDTH_IN * POINTS_PER_INCH
PAGE_HEIGHT_PT = PAGE_HEIGHT_IN * POINTS_PER_INCH
MARGIN_TOP_PT = MARGIN_TOP_IN * POINTS_PER_INCH
MARGIN_BOTTOM_PT = MARGIN_BOTTOM_IN * POINTS_PER_INCH
MARGIN_LEFT_PT = MARGIN_LEFT_IN * POINTS_PER_INCH
MARGIN_RIGHT_PT = MARGIN_RIGHT_IN * POINTS_PER_INCH
CONTENT_WIDTH_PT = PAGE_WIDTH_PT - MARGIN_LEFT_PT - MARGIN_RIGHT_PT

FONT_TITLE_PT = 14.0
FONT_BODY_PT = 11.0
FONT_METADATA_PT = 8.5
FONT_FOOTER_PT = 8.5
FONT_PROVENANCE_PT = 8.5
FONT_BLOCK_HEADER_PT = 10.5
FONT_BLOCK_SUBTITLE_PT = 10.0

TITLE_RULE_GAP_PT = 8.0
TITLE_RULE_THICKNESS_PT = 0.75
TITLE_CONTENT_GAP_PT = 12.0
BLOCK_GAP_PT = 10.0
BLOCK_HEADER_GAP_PT = 5.0
ITEM_SPACING_PT = 4.0
MESSAGE_SPACING_PT = 9.0
MESSAGE_META_GAP_PT = 2.0
MESSAGE_LABEL_GAP_PT = 8.0
MESSAGE_MIN_BODY_INDENT_PT = 72.0
MESSAGE_MAX_BODY_INDENT_PT = 168.0
SECTION_RULE_GAP_PT = 8.0


class FontRole(str, Enum):
    TITLE = "title"
    BLOCK_HEADER = "block_header"
    BLOCK_SUBTITLE = "block_subtitle"
    BODY = "body"
    METADATA = "metadata"
    FOOTER = "footer"
    PROVENANCE = "provenance"


@dataclass(slots=True)
class PrintLayoutItem:
    kind: str
    text: str
    font_role: FontRole
    sender: str = ""
    timestamp: str = ""
    body_lines: tuple[str, ...] = ()
    body_indent_pt: float = 0.0
    is_context: bool = False
    is_highlighted: bool = False


@dataclass(slots=True)
class PrintLayoutPage:
    page_number: int
    title: str
    items: list[PrintLayoutItem]
    footer_exhibit: str
    footer_case: str
    total_pages: int


@dataclass(slots=True)
class PrintLayoutDocument:
    title: str
    exhibit_number: str
    case_number: str
    block_sections: list[PreviewBlockSection]
    provenance_entries: list[PreviewProvenanceEntry]
    pages: list[PrintLayoutPage] = field(default_factory=list)
    footer_exhibit: str = ""
    footer_case: str = ""


class LayoutMetrics(Protocol):
    content_width_pt: float

    def wrap_text(self, role: FontRole, text: str, width_pt: float | None = None) -> list[str]: ...

    def line_height(self, role: FontRole) -> float: ...

    def text_width(self, role: FontRole, text: str) -> float: ...

    def item_height(self, item: PrintLayoutItem) -> float: ...

    def title_block_height(self, title: str) -> float: ...

    def footer_block_height(self) -> float: ...

    def page_content_height(self, title: str) -> float: ...

    def message_body_indent(self, sender: str) -> float: ...

    def wrap_message_body(self, sender: str, body: str) -> tuple[list[str], float]: ...


@dataclass(slots=True)
class RoleMetrics:
    line_height: float
    char_width: float


class StubLayoutMetrics:
    """Fixed metrics for deterministic layout tests without Qt."""

    def __init__(
        self,
        *,
        content_width_pt: float = CONTENT_WIDTH_PT,
        roles: dict[FontRole, RoleMetrics] | None = None,
        footer_lines: int = 3,
    ) -> None:
        default_line = 12.0
        default_char = 6.0
        self.content_width_pt = content_width_pt
        self._roles = roles or {
            FontRole.TITLE: RoleMetrics(line_height=17.0, char_width=default_char),
            FontRole.BLOCK_HEADER: RoleMetrics(line_height=12.0, char_width=default_char),
            FontRole.BLOCK_SUBTITLE: RoleMetrics(line_height=12.0, char_width=default_char),
            FontRole.BODY: RoleMetrics(line_height=12.0, char_width=default_char),
            FontRole.METADATA: RoleMetrics(line_height=10.0, char_width=default_char),
            FontRole.FOOTER: RoleMetrics(line_height=10.0, char_width=default_char),
            FontRole.PROVENANCE: RoleMetrics(line_height=10.0, char_width=default_char),
        }
        self._footer_lines = footer_lines

    def wrap_text(self, role: FontRole, text: str, width_pt: float | None = None) -> list[str]:
        if not text:
            return [""]
        metrics = self._roles[role]
        usable_width = width_pt if width_pt is not None else self.content_width_pt
        max_chars = max(1, int(usable_width / metrics.char_width))
        words = text.split()
        if not words:
            return [""]
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if len(candidate) <= max_chars:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def line_height(self, role: FontRole) -> float:
        return self._roles[role].line_height

    def text_width(self, role: FontRole, text: str) -> float:
        return len(text) * self._roles[role].char_width

    def message_body_indent(self, sender: str) -> float:
        label_width = self.text_width(FontRole.BODY, f"{sender}:")
        return max(
            MESSAGE_MIN_BODY_INDENT_PT,
            min(MESSAGE_MAX_BODY_INDENT_PT, label_width + MESSAGE_LABEL_GAP_PT),
        )

    def wrap_message_body(self, sender: str, body: str) -> tuple[list[str], float]:
        indent_pt = self.message_body_indent(sender)
        usable_width = max(24.0, self.content_width_pt - indent_pt)
        return self.wrap_text(FontRole.BODY, body, usable_width), indent_pt

    def item_height(self, item: PrintLayoutItem) -> float:
        if item.kind == "section_rule":
            return SECTION_RULE_GAP_PT
        if item.kind == "block_header":
            return self.line_height(FontRole.BLOCK_HEADER) + BLOCK_HEADER_GAP_PT
        if item.kind == "block_subtitle":
            lines = self.wrap_text(item.font_role, item.text)
            return len(lines) * self.line_height(item.font_role) + BLOCK_GAP_PT
        if item.kind == "message_block":
            body_lines = list(item.body_lines) or self.wrap_message_body(item.sender, item.text)[0]
            return (
                len(body_lines) * self.line_height(FontRole.BODY)
                + self.line_height(FontRole.METADATA)
                + MESSAGE_META_GAP_PT
                + MESSAGE_SPACING_PT
            )
        if item.kind == "provenance_header":
            return self.line_height(FontRole.BLOCK_HEADER) + BLOCK_HEADER_GAP_PT
        lines = self.wrap_text(item.font_role, item.text)
        return len(lines) * self.line_height(item.font_role) + ITEM_SPACING_PT

    def title_block_height(self, title: str) -> float:
        title_lines = self.wrap_text(FontRole.TITLE, title)
        return (
            len(title_lines) * self.line_height(FontRole.TITLE)
            + TITLE_RULE_GAP_PT
            + TITLE_RULE_THICKNESS_PT
            + TITLE_CONTENT_GAP_PT
        )

    def footer_block_height(self) -> float:
        return self._footer_lines * self.line_height(FontRole.FOOTER) + ITEM_SPACING_PT

    def page_content_height(self, title: str) -> float:
        usable = PAGE_HEIGHT_PT - MARGIN_TOP_PT - MARGIN_BOTTOM_PT
        return usable - self.title_block_height(title) - self.footer_block_height()


class TightPageMetrics(StubLayoutMetrics):
    """Stub metrics that force multi-page layouts in tests."""

    def page_content_height(self, title: str) -> float:
        return 120.0


def _truncate_single_line(text: str, max_chars: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(0, max_chars - 3)].rstrip() + "..."


def _artifact_title(context: PrintableArtifactContext) -> str:
    artifact_title = context.artifact.title.strip()
    if artifact_title:
        return _truncate_single_line(artifact_title, 100)
    if len(context.blocks) == 1:
        block = context.blocks[0].evidence_block
        if block.summary.strip():
            return _truncate_single_line(block.summary, 100)
        if block.title.strip():
            return _truncate_single_line(block.title, 100)
    return "Message Transcript Exhibit"


def _block_heading_text(block: EvidenceBlock) -> str:
    subtitle = block.summary.strip() or block.title.strip()
    return _truncate_single_line(subtitle, 110) if subtitle else ""


def _build_block_sections(context: PrintableArtifactContext) -> list[PreviewBlockSection]:
    sections: list[PreviewBlockSection] = []
    for block_context in context.blocks:
        sections.append(
            PreviewBlockSection(
                label=block_context.block_label,
                title=_block_heading_text(block_context.evidence_block) or block_context.evidence_block.title,
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
    return sections


def _build_provenance_entries(context: PrintableArtifactContext) -> list[PreviewProvenanceEntry]:
    return [
        PreviewProvenanceEntry(
            label=block_context.block_label,
            text=format_block_provenance(
                block_context.block_label,
                build_block_provenance(block_context),
            ),
        )
        for block_context in context.blocks
    ]


def _message_block_item(sender: str, timestamp: str, body: str, metrics: LayoutMetrics) -> PrintLayoutItem:
    body_lines, indent_pt = metrics.wrap_message_body(sender, body)
    return PrintLayoutItem(
        kind="message_block",
        text=body,
        font_role=FontRole.BODY,
        sender=sender,
        timestamp=timestamp,
        body_lines=tuple(body_lines),
        body_indent_pt=indent_pt,
    )


def _build_layout_items(context: PrintableArtifactContext, metrics: LayoutMetrics) -> list[PrintLayoutItem]:
    items: list[PrintLayoutItem] = []
    for block_index, block_context in enumerate(context.blocks):
        if block_index > 0:
            items.append(PrintLayoutItem("section_rule", "", FontRole.BLOCK_HEADER))
        items.append(PrintLayoutItem("block_header", f"Block {block_context.block_label}", FontRole.BLOCK_HEADER))
        subtitle = _block_heading_text(block_context.evidence_block)
        if subtitle:
            items.append(PrintLayoutItem("block_subtitle", subtitle, FontRole.BLOCK_SUBTITLE))
        for index, message in enumerate(block_context.messages):
            slot = block_context.evidence_block.context_start_slot + index
            is_context = (
                slot < block_context.evidence_block.relevant_start_slot
                or slot >= block_context.evidence_block.relevant_end_slot
            )
            item = _message_block_item(
                message.sender_display or message.sender_id,
                message.timestamp,
                message.body,
                metrics,
            )
            item.is_context = is_context
            item.is_highlighted = message.message_id in block_context.evidence_block.highlighted_message_ids
            items.append(item)

    if context.blocks:
        items.append(PrintLayoutItem("section_rule", "", FontRole.BLOCK_HEADER))
        items.append(PrintLayoutItem("provenance_header", "Provenance", FontRole.BLOCK_HEADER))
        for block_context in context.blocks:
            ledger = format_block_provenance(
                block_context.block_label,
                build_block_provenance(block_context),
            )
            items.append(PrintLayoutItem("provenance_entry", ledger, FontRole.PROVENANCE))
    return items


def _paginate_items(
    *,
    title: str,
    items: list[PrintLayoutItem],
    metrics: LayoutMetrics,
    footer_exhibit: str,
    footer_case: str,
) -> list[PrintLayoutPage]:
    content_height = metrics.page_content_height(title)
    page_items: list[PrintLayoutItem] = []
    used_height = 0.0
    pages: list[list[PrintLayoutItem]] = []

    for item in items:
        item_height = metrics.item_height(item)
        if page_items and used_height + item_height > content_height:
            pages.append(page_items)
            page_items = []
            used_height = 0.0
        page_items.append(item)
        used_height += item_height

    if page_items or not pages:
        pages.append(page_items)

    total_pages = max(1, len(pages))
    return [
        PrintLayoutPage(
            page_number=index + 1,
            title=title,
            items=page_item_list,
            footer_exhibit=footer_exhibit,
            footer_case=footer_case,
            total_pages=total_pages,
        )
        for index, page_item_list in enumerate(pages)
    ]


def build_print_layout(
    context: PrintableArtifactContext,
    metrics: LayoutMetrics | None = None,
) -> PrintLayoutDocument:
    layout_metrics = metrics or StubLayoutMetrics()
    title = _artifact_title(context)
    footer_exhibit = context.artifact.exhibit_number
    footer_case = context.artifact.case_number
    items = _build_layout_items(context, layout_metrics)
    pages = _paginate_items(
        title=title,
        items=items,
        metrics=layout_metrics,
        footer_exhibit=footer_exhibit,
        footer_case=footer_case,
    )
    return PrintLayoutDocument(
        title=title,
        exhibit_number=context.artifact.exhibit_number,
        case_number=context.artifact.case_number,
        block_sections=_build_block_sections(context),
        provenance_entries=_build_provenance_entries(context),
        pages=pages,
        footer_exhibit=footer_exhibit,
        footer_case=footer_case,
    )

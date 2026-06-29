"""Qt rendering and PDF export for measured print layouts."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen
from PySide6.QtPrintSupport import QPrinter

from message_evidence_workstation.output.print_layout import (
    BLOCK_HEADER_GAP_PT,
    CONTENT_WIDTH_PT,
    FONT_BLOCK_HEADER_PT,
    FONT_BLOCK_SUBTITLE_PT,
    ITEM_SPACING_PT,
    FONT_BODY_PT,
    FONT_FOOTER_PT,
    FONT_METADATA_PT,
    FONT_PROVENANCE_PT,
    FONT_TITLE_PT,
    MARGIN_BOTTOM_PT,
    MARGIN_LEFT_PT,
    MARGIN_RIGHT_PT,
    MARGIN_TOP_PT,
    PAGE_HEIGHT_PT,
    PAGE_WIDTH_PT,
    SECTION_RULE_GAP_PT,
    TITLE_CONTENT_GAP_PT,
    TITLE_RULE_GAP_PT,
    TITLE_RULE_THICKNESS_PT,
    FontRole,
    LayoutMetrics,
    PrintLayoutDocument,
    PrintLayoutItem,
    PrintLayoutPage,
    StubLayoutMetrics,
)

HEADER_RULE_COLOR = QColor("#202020")
SECTION_RULE_COLOR = QColor("#A8AAA7")
METADATA_TEXT_COLOR = QColor("#54514B")
FOOTER_TEXT_COLOR = QColor("#44413C")
BODY_TEXT_COLOR = QColor("#111111")
CONTEXT_TEXT_COLOR = QColor("#77746D")
CONTEXT_METADATA_COLOR = QColor("#908C84")
HIGHLIGHT_FILL_COLOR = QColor("#FFF6C7")


def _font_for_role(role: FontRole) -> QFont:
    font = QFont("Georgia")
    if role is FontRole.TITLE:
        font.setPointSizeF(FONT_TITLE_PT)
        font.setBold(True)
    elif role is FontRole.BLOCK_HEADER:
        font.setPointSizeF(FONT_BLOCK_HEADER_PT)
        font.setBold(True)
    elif role is FontRole.BLOCK_SUBTITLE:
        font.setPointSizeF(FONT_BLOCK_SUBTITLE_PT)
    elif role is FontRole.BODY:
        font.setPointSizeF(FONT_BODY_PT)
    elif role is FontRole.METADATA:
        font.setPointSizeF(FONT_METADATA_PT)
    elif role is FontRole.FOOTER:
        font.setPointSizeF(FONT_FOOTER_PT)
    elif role is FontRole.PROVENANCE:
        font.setPointSizeF(FONT_PROVENANCE_PT)
    return font


class QtLayoutMetrics(StubLayoutMetrics):
    """Layout metrics backed by QFontMetrics."""

    def __init__(self) -> None:
        from PySide6.QtGui import QFontMetricsF

        super().__init__(content_width_pt=CONTENT_WIDTH_PT)
        self.content_width_pt = CONTENT_WIDTH_PT
        self._fonts = {role: _font_for_role(role) for role in FontRole}
        self._metrics = {role: QFontMetricsF(font) for role, font in self._fonts.items()}

    def wrap_text(self, role: FontRole, text: str, width_pt: float | None = None) -> list[str]:
        if not text:
            return [""]
        metrics = self._metrics[role]
        usable_width = width_pt if width_pt is not None else self.content_width_pt
        words = text.split()
        if not words:
            return [""]
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if metrics.horizontalAdvance(candidate) <= usable_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def line_height(self, role: FontRole) -> float:
        return float(self._metrics[role].lineSpacing())

    def text_width(self, role: FontRole, text: str) -> float:
        return float(self._metrics[role].horizontalAdvance(text))


def _draw_horizontal_rule(painter: QPainter, y: float, *, color: QColor, width_pt: float) -> None:
    pen = QPen(color)
    pen.setWidthF(width_pt)
    painter.setPen(pen)
    painter.drawLine(MARGIN_LEFT_PT, y, PAGE_WIDTH_PT - MARGIN_RIGHT_PT, y)


def _draw_wrapped_text(
    painter: QPainter,
    metrics: LayoutMetrics,
    role: FontRole,
    text: str,
    *,
    x: float,
    y: float,
    width_pt: float,
) -> float:
    painter.setFont(_font_for_role(role))
    lines = metrics.wrap_text(role, text, width_pt)
    cursor_y = y
    for line in lines:
        painter.drawText(
            QRectF(x, cursor_y, width_pt, metrics.line_height(role)),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            line,
        )
        cursor_y += metrics.line_height(role)
    return cursor_y


def _paint_message_block(
    painter: QPainter,
    item: PrintLayoutItem,
    cursor_y: float,
    metrics: LayoutMetrics,
) -> float:
    sender_label = f"{item.sender}:"
    sender_width = metrics.text_width(FontRole.BODY, sender_label)
    body_x = MARGIN_LEFT_PT + item.body_indent_pt
    body_width = max(24.0, CONTENT_WIDTH_PT - item.body_indent_pt)
    body_lines = list(item.body_lines) or metrics.wrap_message_body(item.sender, item.text)[0]
    block_height = metrics.item_height(item)

    if item.is_highlighted:
        painter.fillRect(
            QRectF(MARGIN_LEFT_PT - 6.0, cursor_y - 2.0, CONTENT_WIDTH_PT + 12.0, block_height - 2.0),
            HIGHLIGHT_FILL_COLOR,
        )

    painter.setPen(CONTEXT_TEXT_COLOR if item.is_context else BODY_TEXT_COLOR)
    body_font = _font_for_role(FontRole.BODY)
    body_font.setBold(item.is_highlighted)
    painter.setFont(body_font)
    painter.drawText(
        QRectF(MARGIN_LEFT_PT, cursor_y, sender_width, metrics.line_height(FontRole.BODY)),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        sender_label,
    )

    for index, line in enumerate(body_lines):
        line_y = cursor_y + index * metrics.line_height(FontRole.BODY)
        painter.drawText(
            QRectF(body_x, line_y, body_width, metrics.line_height(FontRole.BODY)),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            line,
        )

    cursor_y += len(body_lines) * metrics.line_height(FontRole.BODY)
    painter.setPen(CONTEXT_METADATA_COLOR if item.is_context else METADATA_TEXT_COLOR)
    painter.setFont(_font_for_role(FontRole.METADATA))
    painter.drawText(
        QRectF(MARGIN_LEFT_PT, cursor_y + 2.0, CONTENT_WIDTH_PT, metrics.line_height(FontRole.METADATA)),
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
        item.timestamp,
    )
    return cursor_y + metrics.line_height(FontRole.METADATA) + 2.0 + 9.0


def paint_layout_page(
    painter: QPainter,
    page: PrintLayoutPage,
    *,
    metrics: LayoutMetrics | None = None,
) -> None:
    qt_metrics = metrics if metrics is not None else QtLayoutMetrics()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setPen(BODY_TEXT_COLOR)

    title_width = CONTENT_WIDTH_PT
    painter.setFont(_font_for_role(FontRole.TITLE))
    title_lines = qt_metrics.wrap_text(FontRole.TITLE, page.title, title_width)
    cursor_y = MARGIN_TOP_PT
    for line in title_lines:
        painter.drawText(
            QRectF(MARGIN_LEFT_PT, cursor_y, title_width, qt_metrics.line_height(FontRole.TITLE)),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            line,
        )
        cursor_y += qt_metrics.line_height(FontRole.TITLE)

    cursor_y += TITLE_RULE_GAP_PT
    _draw_horizontal_rule(painter, cursor_y, color=HEADER_RULE_COLOR, width_pt=TITLE_RULE_THICKNESS_PT)
    cursor_y += TITLE_CONTENT_GAP_PT

    content_bottom = PAGE_HEIGHT_PT - MARGIN_BOTTOM_PT - qt_metrics.footer_block_height()

    for item in page.items:
        if item.kind == "section_rule":
            cursor_y += SECTION_RULE_GAP_PT / 2.0
            _draw_horizontal_rule(painter, cursor_y, color=SECTION_RULE_COLOR, width_pt=0.6)
            cursor_y += SECTION_RULE_GAP_PT / 2.0
            continue
        if item.kind == "block_header":
            painter.setPen(BODY_TEXT_COLOR)
            cursor_y = _draw_wrapped_text(
                painter,
                qt_metrics,
                FontRole.BLOCK_HEADER,
                item.text,
                x=MARGIN_LEFT_PT,
                y=cursor_y,
                width_pt=CONTENT_WIDTH_PT,
            )
            cursor_y += BLOCK_HEADER_GAP_PT
            continue
        if item.kind == "block_subtitle":
            painter.setPen(BODY_TEXT_COLOR)
            cursor_y = _draw_wrapped_text(
                painter,
                qt_metrics,
                FontRole.BLOCK_SUBTITLE,
                item.text,
                x=MARGIN_LEFT_PT,
                y=cursor_y,
                width_pt=CONTENT_WIDTH_PT,
            )
            cursor_y += 10.0
            continue
        if item.kind == "message_block":
            if cursor_y + qt_metrics.item_height(item) > content_bottom:
                break
            cursor_y = _paint_message_block(painter, item, cursor_y, qt_metrics)
            continue
        if item.kind == "provenance_header":
            painter.setPen(BODY_TEXT_COLOR)
            cursor_y = _draw_wrapped_text(
                painter,
                qt_metrics,
                FontRole.BLOCK_HEADER,
                item.text,
                x=MARGIN_LEFT_PT,
                y=cursor_y,
                width_pt=CONTENT_WIDTH_PT,
            )
            cursor_y += BLOCK_HEADER_GAP_PT
            continue

        painter.setPen(FOOTER_TEXT_COLOR if item.kind == "provenance_entry" else BODY_TEXT_COLOR)
        cursor_y = _draw_wrapped_text(
            painter,
            qt_metrics,
            item.font_role,
            item.text,
            x=MARGIN_LEFT_PT,
            y=cursor_y,
            width_pt=CONTENT_WIDTH_PT,
        )
        cursor_y += ITEM_SPACING_PT

    footer_top = PAGE_HEIGHT_PT - MARGIN_BOTTOM_PT - qt_metrics.footer_block_height() + 2.0
    _draw_horizontal_rule(painter, footer_top - 6.0, color=SECTION_RULE_COLOR, width_pt=0.6)
    painter.setPen(FOOTER_TEXT_COLOR)
    painter.setFont(_font_for_role(FontRole.FOOTER))
    footer_lines = [
        f"Exhibit: {page.footer_exhibit or '-'}",
        f"Case: {page.footer_case or '-'}",
        f"Page {page.page_number} of {page.total_pages}",
    ]
    footer_y = footer_top
    for line in footer_lines:
        painter.drawText(
            QRectF(
                MARGIN_LEFT_PT,
                footer_y,
                PAGE_WIDTH_PT - MARGIN_LEFT_PT - MARGIN_RIGHT_PT,
                qt_metrics.line_height(FontRole.FOOTER),
            ),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
            line,
        )
        footer_y += qt_metrics.line_height(FontRole.FOOTER)


def export_layout_to_pdf(document: PrintLayoutDocument, path: Path | str) -> None:
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.Letter))
    writer.setResolution(300)
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
    painter = QPainter(writer)
    scale = writer.resolution() / 72.0
    painter.scale(scale, scale)
    metrics = QtLayoutMetrics()
    for index, page in enumerate(document.pages):
        if index > 0:
            writer.newPage()
            painter.scale(scale, scale)
        paint_layout_page(painter, page, metrics=metrics)
    painter.end()


def print_layout_document(document: PrintLayoutDocument, printer: QPrinter) -> None:
    painter = QPainter(printer)
    dpi_x = printer.logicalDpiX() or 72
    dpi_y = printer.logicalDpiY() or 72
    painter.scale(dpi_x / 72.0, dpi_y / 72.0)
    metrics = QtLayoutMetrics()
    for index, page in enumerate(document.pages):
        if index > 0:
            printer.newPage()
            painter.scale(dpi_x / 72.0, dpi_y / 72.0)
        paint_layout_page(painter, page, metrics=metrics)
    painter.end()

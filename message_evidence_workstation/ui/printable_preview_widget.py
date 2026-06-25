"""Paged preview widget for printable artifacts."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.output.printable_preview import PrintablePreviewModel


class PrintablePreviewWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model: PrintablePreviewModel | None = None
        self._page_index = 0
        self._zoom_percent = 100

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.prev_button = QPushButton("Previous")
        self.prev_button.clicked.connect(self.show_previous_page)
        controls.addWidget(self.prev_button)
        self.page_label = QLabel("—")
        controls.addWidget(self.page_label)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.show_next_page)
        controls.addWidget(self.next_button)
        controls.addStretch()
        self.zoom_out_button = QPushButton("Zoom out")
        self.zoom_out_button.clicked.connect(self.zoom_out)
        controls.addWidget(self.zoom_out_button)
        self.zoom_label = QLabel("100%")
        controls.addWidget(self.zoom_label)
        self.zoom_in_button = QPushButton("Zoom in")
        self.zoom_in_button.clicked.connect(self.zoom_in)
        controls.addWidget(self.zoom_in_button)
        layout.addLayout(controls)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.page_container = QWidget()
        self.page_layout = QVBoxLayout(self.page_container)
        self.title_label = QLabel()
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.body_label = QLabel()
        self.body_label.setWordWrap(True)
        self.body_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.footer_label = QLabel()
        self.footer_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.page_layout.addWidget(self.title_label)
        self.page_layout.addWidget(self.body_label, stretch=1)
        self.page_layout.addWidget(self.footer_label)
        self.scroll_area.setWidget(self.page_container)
        layout.addWidget(self.scroll_area, stretch=1)

        self.empty_label = QLabel("Select a printable artifact to preview.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)
        self._set_preview_visible(False)

    def set_preview_model(self, model: PrintablePreviewModel | None) -> None:
        self._model = model
        self._page_index = 0
        if model is None or not model.pages:
            self._set_preview_visible(False)
            self.empty_label.setText("Select a printable artifact to preview.")
            self.empty_label.show()
            return
        self.empty_label.hide()
        self._set_preview_visible(True)
        self._render_current_page()

    def show_previous_page(self) -> None:
        if self._model is None or self._page_index <= 0:
            return
        self._page_index -= 1
        self._render_current_page()

    def show_next_page(self) -> None:
        if self._model is None or self._page_index >= len(self._model.pages) - 1:
            return
        self._page_index += 1
        self._render_current_page()

    def zoom_in(self) -> None:
        self._zoom_percent = min(200, self._zoom_percent + 10)
        self._apply_zoom()

    def zoom_out(self) -> None:
        self._zoom_percent = max(50, self._zoom_percent - 10)
        self._apply_zoom()

    def _set_preview_visible(self, visible: bool) -> None:
        self.scroll_area.setVisible(visible)
        self.prev_button.setEnabled(visible)
        self.next_button.setEnabled(visible)
        self.zoom_in_button.setEnabled(visible)
        self.zoom_out_button.setEnabled(visible)
        if not visible:
            self.page_label.setText("—")
            self.zoom_label.setText("100%")

    def _apply_zoom(self) -> None:
        self.zoom_label.setText(f"{self._zoom_percent}%")
        base = 11
        size = max(8, int(base * self._zoom_percent / 100))
        title_font = QFont()
        title_font.setPointSize(size + 3)
        title_font.setBold(True)
        body_font = QFont()
        body_font.setPointSize(size)
        footer_font = QFont()
        footer_font.setPointSize(max(8, size - 1))
        self.title_label.setFont(title_font)
        self.body_label.setFont(body_font)
        self.footer_label.setFont(footer_font)

    def _render_current_page(self) -> None:
        if self._model is None or not self._model.pages:
            return
        page = self._model.pages[self._page_index]
        total = len(self._model.pages)
        self.page_label.setText(f"{page.page_number} / {total}")
        self.prev_button.setEnabled(self._page_index > 0)
        self.next_button.setEnabled(self._page_index < total - 1)

        self.title_label.setVisible(True)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setText(self._model.title)

        body_parts: list[str] = []
        for line in page.lines:
            if line.kind == "title":
                continue
            text = escape(line.text)
            if line.kind == "message_meta":
                body_parts.append(f"<span style='color:#666;font-size:smaller'><i>{text}</i></span>")
            elif line.kind == "block_label":
                body_parts.append(f"<b>{text}</b>")
            elif line.kind == "block_title":
                body_parts.append(f"<b>{text}</b>")
            elif line.kind == "provenance_header":
                body_parts.append(f"<br/><b>{text}</b>")
            elif line.kind == "provenance_entry":
                body_parts.append(text)
            elif line.kind == "blank":
                body_parts.append("<br/>")
            else:
                body_parts.append(text)
        self.body_label.setText("<br/>".join(body_parts))

        exhibit = self._model.footer_exhibit or "—"
        case = self._model.footer_case or "—"
        self.footer_label.setText(
            f"Exhibit: {escape(exhibit)}<br/>Case: {escape(case)}<br/>Page {page.page_number} of {total}"
        )
        self._apply_zoom()

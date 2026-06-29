"""WYSIWYG print preview widget for printable artifacts."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QFileDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from message_evidence_workstation.output.print_layout import (
    PAGE_HEIGHT_PT,
    PAGE_WIDTH_PT,
    PrintLayoutDocument,
)
from message_evidence_workstation.output.print_layout_render import (
    export_layout_to_pdf,
    paint_layout_page,
    print_layout_document,
)


class PrintPreviewWidget(QWidget):
    PREVIEW_DEVICE_SCALE = 3.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document: PrintLayoutDocument | None = None
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
        self.print_button = QPushButton("Print")
        self.print_button.clicked.connect(self.print_document)
        controls.addWidget(self.print_button)
        self.export_pdf_button = QPushButton("Export PDF")
        self.export_pdf_button.clicked.connect(self.export_pdf)
        controls.addWidget(self.export_pdf_button)
        layout.addLayout(controls)

        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        layout.addWidget(self.view, stretch=1)

        self.empty_label = QLabel("Select a printable artifact to preview.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)
        self._page_item: QGraphicsPixmapItem | None = None
        self._set_preview_visible(False)

    def set_layout_document(self, document: PrintLayoutDocument | None) -> None:
        self._document = document
        self._page_index = 0
        if document is None or not document.pages:
            self._set_preview_visible(False)
            self.empty_label.setText("Select a printable artifact to preview.")
            self.empty_label.show()
            return
        self.empty_label.hide()
        self._set_preview_visible(True)
        self._render_current_page()

    def set_preview_model(self, document: PrintLayoutDocument | None) -> None:
        """Backward-compatible alias for tab wiring."""
        self.set_layout_document(document)

    def show_previous_page(self) -> None:
        if self._document is None or self._page_index <= 0:
            return
        self._page_index -= 1
        self._render_current_page()

    def show_next_page(self) -> None:
        if self._document is None or self._page_index >= len(self._document.pages) - 1:
            return
        self._page_index += 1
        self._render_current_page()

    def zoom_in(self) -> None:
        self._zoom_percent = min(200, self._zoom_percent + 10)
        self._render_current_page()

    def zoom_out(self) -> None:
        self._zoom_percent = max(50, self._zoom_percent - 10)
        self._render_current_page()

    def print_document(self) -> None:
        if self._document is None or not self._document.pages:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageSize(QPrinter.PageSize.Letter)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return
        print_layout_document(self._document, printer)

    def export_pdf(self) -> None:
        if self._document is None or not self._document.pages:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", "", "PDF Files (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path = f"{path}.pdf"
        export_layout_to_pdf(self._document, Path(path))

    def _set_preview_visible(self, visible: bool) -> None:
        self.view.setVisible(visible)
        self.prev_button.setEnabled(visible)
        self.next_button.setEnabled(visible)
        self.zoom_in_button.setEnabled(visible)
        self.zoom_out_button.setEnabled(visible)
        self.print_button.setEnabled(visible)
        self.export_pdf_button.setEnabled(visible)
        if not visible:
            self.page_label.setText("—")
            self.zoom_label.setText("100%")
            self.scene.clear()
            self._page_item = None

    def _render_current_page(self) -> None:
        if self._document is None or not self._document.pages:
            return
        page = self._document.pages[self._page_index]
        total = len(self._document.pages)
        self.page_label.setText(f"{page.page_number} / {total}")
        self.prev_button.setEnabled(self._page_index > 0)
        self.next_button.setEnabled(self._page_index < total - 1)
        self.zoom_label.setText(f"{self._zoom_percent}%")

        logical_width = int(PAGE_WIDTH_PT)
        logical_height = int(PAGE_HEIGHT_PT)
        physical_width = int(logical_width * self.PREVIEW_DEVICE_SCALE)
        physical_height = int(logical_height * self.PREVIEW_DEVICE_SCALE)

        pixmap = QPixmap(physical_width, physical_height)
        pixmap.setDevicePixelRatio(self.PREVIEW_DEVICE_SCALE)
        pixmap.fill(Qt.GlobalColor.white)
        painter = QPainter(pixmap)
        paint_layout_page(painter, page)
        painter.end()

        self.scene.clear()
        self._page_item = self.scene.addPixmap(pixmap)
        self.scene.setSceneRect(0, 0, logical_width, logical_height)
        self.view.resetTransform()
        scale = self._zoom_percent / 100.0
        self.view.scale(scale, scale)
        self.view.centerOn(self._page_item)

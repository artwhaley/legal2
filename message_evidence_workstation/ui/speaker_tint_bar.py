"""Editable participant tint swatches for the transcript widget."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QHBoxLayout, QLabel, QPushButton, QWidget

from message_evidence_workstation.ui.transcript_display import normalize_speaker_tints


class SpeakerTintBar(QWidget):
    tints_changed = Signal(list)

    def __init__(self, tints: list[str] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tints = normalize_speaker_tints(tints)
        self._buttons: list[QPushButton] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Participant tints"))
        for index, color in enumerate(self._tints):
            button = QPushButton()
            button.setFixedSize(22, 22)
            button.setToolTip(f"Participant {index + 1} background")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, idx=index: self._pick_color(idx))
            self._buttons.append(button)
            layout.addWidget(button)
        layout.addStretch()
        self._apply_button_styles()

    def tints(self) -> list[str]:
        return list(self._tints)

    def set_tints(self, tints: list[str]) -> None:
        self._tints = normalize_speaker_tints(tints)
        self._apply_button_styles()

    def _pick_color(self, index: int) -> None:
        initial = QColor(self._tints[index])
        chosen = QColorDialog.getColor(initial, self, f"Participant {index + 1} tint")
        if not chosen.isValid():
            return
        self._tints[index] = chosen.name(QColor.NameFormat.HexRgb)
        self._apply_button_styles()
        self.tints_changed.emit(self.tints())

    def _apply_button_styles(self) -> None:
        for index, button in enumerate(self._buttons):
            color = self._tints[index]
            button.setStyleSheet(
                f"QPushButton {{ background-color: {color}; border: 1px solid #9a9488; border-radius: 3px; }}"
            )

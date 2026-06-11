from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QLabel, QLineEdit, QMainWindow, QVBoxLayout, QWidget


class MainView(QMainWindow):
    closing = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BT Random Data")
        self.setMinimumSize(360, 220)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("Random Data")
        title.setObjectName("title")
        layout.addWidget(title)

        self._textboxes = [QLineEdit() for _ in range(3)]
        for textbox in self._textboxes:
            textbox.setReadOnly(True)
            textbox.setMinimumHeight(40)
            layout.addWidget(textbox)

        self.setCentralWidget(root)
        self.setStyleSheet(
            """
            QMainWindow {
                background: #f7f8fa;
            }
            QLabel#title {
                color: #172033;
                font-size: 18px;
                font-weight: 600;
            }
            QLineEdit {
                background: white;
                border: 1px solid #cfd6df;
                border-radius: 6px;
                color: #172033;
                font-size: 15px;
                padding: 8px 10px;
            }
            """
        )

    def set_values(self, values: tuple[str, str, str]) -> None:
        for textbox, value in zip(self._textboxes, values, strict=True):
            textbox.setText(value)

    def closeEvent(self, event) -> None:  # noqa: N802, ANN001
        self.closing.emit()
        super().closeEvent(event)


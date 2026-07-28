"""Trang cấu hình BAT mở Trợ lý ảo và thư mục Output."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


def _setting(source: Any, name: str, default: Any = "") -> Any:
    if source is None:
        return default
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


class SettingsPage(QWidget):
    save_requested = Signal(object)
    check_requested = Signal(object)
    open_output_requested = Signal(object)

    def __init__(self, settings: Any | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self._connect_signals()
        self.set_settings(settings)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)
        scroll.setWidget(body)

        title = QLabel("Cài đặt")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Chọn file BAT mở Trợ lý ảo và thư mục nhận kết quả Output."
        )
        subtitle.setProperty("muted", True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        card = QFrame()
        card.setProperty("card", True)
        card_layout = QVBoxLayout(card)
        form = QFormLayout()
        form.setHorizontalSpacing(15)
        form.setVerticalSpacing(12)

        bat_row = QHBoxLayout()
        self.bat_edit = QLineEdit()
        self.bat_edit.setObjectName("assistantBatEdit")
        self.bat_edit.setPlaceholderText("Chọn Mo_Tro_Ly_RPA.bat")
        self.bat_edit.setClearButtonEnabled(True)
        self.browse_bat_button = QPushButton("Chọn…")
        bat_row.addWidget(self.bat_edit, 1)
        bat_row.addWidget(self.browse_bat_button)
        bat_widget = QWidget()
        bat_widget.setLayout(bat_row)
        form.addRow("File .bat mở Trợ lý ảo:", bat_widget)

        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setObjectName("outputDirEdit")
        self.output_edit.setClearButtonEnabled(True)
        self.browse_output_button = QPushButton("Chọn…")
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(self.browse_output_button)
        output_widget = QWidget()
        output_widget.setLayout(output_row)
        form.addRow("Thư mục Output:", output_widget)
        card_layout.addLayout(form)
        layout.addWidget(card)

        self.validation_label = QLabel()
        self.validation_label.setObjectName("settingsValidationLabel")
        self.validation_label.setWordWrap(True)
        layout.addWidget(self.validation_label)

        buttons = QHBoxLayout()
        self.check_button = QPushButton("Kiểm tra cấu hình")
        self.open_output_button = QPushButton("Mở thư mục Output")
        self.save_button = QPushButton("Lưu cấu hình")
        self.save_button.setObjectName("saveSettingsButton")
        self.save_button.setProperty("primary", True)
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.open_output_button)
        buttons.addStretch()
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        layout.addStretch()

    def _connect_signals(self) -> None:
        self.browse_bat_button.clicked.connect(self._browse_bat)
        self.browse_output_button.clicked.connect(self._browse_output)
        self.save_button.clicked.connect(self._request_save)
        self.check_button.clicked.connect(
            lambda: self.check_requested.emit(self.settings_data())
        )
        self.open_output_button.clicked.connect(
            lambda: self.open_output_requested.emit(
                Path(self.output_edit.text().strip())
            )
        )
        self.bat_edit.textChanged.connect(self._validate_form)
        self.output_edit.textChanged.connect(self._validate_form)

    def set_settings(self, settings: Any | None) -> None:
        self.bat_edit.setText(str(_setting(settings, "assistant_bat_path") or ""))
        self.output_edit.setText(str(_setting(settings, "output_dir") or ""))
        self._validate_form()

    def settings_data(self) -> dict[str, Any]:
        return {
            "assistant_bat_path": self.bat_edit.text().strip(),
            "output_dir": self.output_edit.text().strip(),
        }

    values = settings_data

    def _validate_form(self, *_args: Any) -> bool:
        bat_text = self.bat_edit.text().strip()
        output_text = self.output_edit.text().strip()
        problems: list[str] = []
        if not bat_text:
            problems.append("Cần chọn file BAT mở Trợ lý ảo.")
        elif Path(bat_text).suffix.casefold() != ".bat":
            problems.append("File mở Trợ lý ảo phải có đuôi .bat.")
        elif not Path(bat_text).is_file():
            problems.append("Không tìm thấy file BAT đã chọn.")
        if not output_text:
            problems.append("Cần chọn thư mục Output.")

        valid = not problems
        self.save_button.setEnabled(valid)
        self.check_button.setEnabled(valid)
        self.open_output_button.setEnabled(bool(output_text))
        self.validation_label.setText(
            " • ".join(problems) if problems else "Cấu hình hợp lệ."
        )
        self.validation_label.setProperty("status", "error" if problems else "success")
        self.validation_label.style().unpolish(self.validation_label)
        self.validation_label.style().polish(self.validation_label)
        return valid

    def _request_save(self) -> None:
        if self._validate_form():
            self.save_requested.emit(self.settings_data())

    def mark_saved(self, settings: Any | None = None) -> None:
        if settings is not None:
            self.set_settings(settings)
        self.validation_label.setText("Đã lưu cấu hình.")
        self.validation_label.setProperty("status", "success")
        self.validation_label.style().unpolish(self.validation_label)
        self.validation_label.style().polish(self.validation_label)

    def show_check_result(self, success: bool, message: str) -> None:
        self.validation_label.setText(message)
        self.validation_label.setProperty("status", "success" if success else "error")
        self.validation_label.style().unpolish(self.validation_label)
        self.validation_label.style().polish(self.validation_label)

    def _browse_bat(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file BAT mở Trợ lý ảo",
            self.bat_edit.text().strip(),
            "Batch Windows (*.bat)",
        )
        if filename:
            self.bat_edit.setText(filename)

    def _browse_output(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục Output",
            self.output_edit.text().strip(),
        )
        if directory:
            self.output_edit.setText(directory)

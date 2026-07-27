"""Trang cấu hình GPT, trình duyệt, Inbox và file watcher."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def _setting(source: Any, *names: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, Mapping):
        for name in names:
            if name in source:
                return source[name]
        return default
    for name in names:
        if hasattr(source, name):
            value = getattr(source, name)
            return value.value if hasattr(value, "value") else value
    return default


class SettingsPage(QWidget):
    """Form settings độc lập với cách lưu; MainWindow nhận signal và gọi ConfigManager."""

    save_requested = Signal(object)
    test_gpt_requested = Signal(object)
    detect_browser_requested = Signal()
    open_inbox_requested = Signal(object)

    def __init__(self, settings: Any | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loaded_inbox = ""
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
            "Các đường dẫn đều có thể thay đổi. Khi đổi Inbox, ứng dụng sẽ khởi động "
            "lại bộ theo dõi mà không cần thoát."
        )
        subtitle.setProperty("muted", True)
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        card = QFrame()
        card.setProperty("card", True)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        form = QFormLayout()
        form.setHorizontalSpacing(15)
        form.setVerticalSpacing(11)

        self.gpt_url_edit = QLineEdit()
        self.gpt_url_edit.setObjectName("gptUrlEdit")
        self.gpt_url_edit.setPlaceholderText("https://chatgpt.com/g/g-... (URL GPT Custom của bạn)")
        self.gpt_url_edit.setClearButtonEnabled(True)
        form.addRow("URL GPT Custom:", self.gpt_url_edit)

        self.browser_combo = QComboBox()
        self.browser_combo.setObjectName("browserPreferenceCombo")
        self.browser_combo.addItem("Tự động", "auto")
        self.browser_combo.addItem("Google Chrome", "chrome")
        self.browser_combo.addItem("Microsoft Edge", "edge")
        self.browser_combo.addItem("Mặc định Windows", "default")
        form.addRow("Trình duyệt ưu tiên:", self.browser_combo)

        executable_row = QHBoxLayout()
        executable_row.setContentsMargins(0, 0, 0, 0)
        self.executable_edit = QLineEdit()
        self.executable_edit.setObjectName("browserExecutableEdit")
        self.executable_edit.setPlaceholderText("Để trống để ứng dụng tự dò")
        self.executable_edit.setClearButtonEnabled(True)
        self.browse_executable_button = QPushButton("Duyệt…")
        self.detect_button = QPushButton("Tự dò")
        self.detect_button.setObjectName("detectBrowserButton")
        executable_row.addWidget(self.executable_edit, 1)
        executable_row.addWidget(self.browse_executable_button)
        executable_row.addWidget(self.detect_button)
        executable_widget = QWidget()
        executable_widget.setLayout(executable_row)
        form.addRow("Executable trình duyệt:", executable_widget)

        profile_row = QHBoxLayout()
        profile_row.setContentsMargins(0, 0, 0, 0)
        self.profile_edit = QLineEdit()
        self.profile_edit.setObjectName("browserProfileEdit")
        self.profile_edit.setClearButtonEnabled(True)
        self.browse_profile_button = QPushButton("Duyệt…")
        profile_row.addWidget(self.profile_edit, 1)
        profile_row.addWidget(self.browse_profile_button)
        profile_widget = QWidget()
        profile_widget.setLayout(profile_row)
        form.addRow("Thư mục browser profile:", profile_widget)

        inbox_row = QHBoxLayout()
        inbox_row.setContentsMargins(0, 0, 0, 0)
        self.inbox_edit = QLineEdit()
        self.inbox_edit.setObjectName("inboxEdit")
        self.inbox_edit.setClearButtonEnabled(True)
        self.browse_inbox_button = QPushButton("Duyệt…")
        inbox_row.addWidget(self.inbox_edit, 1)
        inbox_row.addWidget(self.browse_inbox_button)
        inbox_widget = QWidget()
        inbox_widget.setLayout(inbox_row)
        form.addRow("Thư mục Inbox:", inbox_widget)

        self.pattern_edit = QLineEdit()
        self.pattern_edit.setObjectName("filenamePatternEdit")
        self.pattern_edit.setPlaceholderText("ket_qua_boc_tach*.json")
        form.addRow("Pattern tên file:", self.pattern_edit)

        self.stability_spin = QDoubleSpinBox()
        self.stability_spin.setObjectName("stabilitySecondsSpin")
        self.stability_spin.setRange(0.0, 120.0)
        self.stability_spin.setDecimals(1)
        self.stability_spin.setSingleStep(0.5)
        self.stability_spin.setSuffix(" giây")
        form.addRow("Thời gian file ổn định:", self.stability_spin)

        self.max_size_spin = QSpinBox()
        self.max_size_spin.setObjectName("maxFileSizeSpin")
        self.max_size_spin.setRange(1, 4096)
        self.max_size_spin.setSuffix(" MB")
        form.addRow("Kích thước file tối đa:", self.max_size_spin)

        self.auto_open_check = QCheckBox("Tự động mở cửa sổ review khi nhận file")
        self.auto_open_check.setObjectName("autoOpenReviewCheck")
        form.addRow("Sau khi nhận file:", self.auto_open_check)
        card_layout.addLayout(form)
        layout.addWidget(card)

        self.validation_label = QLabel()
        self.validation_label.setObjectName("settingsValidationLabel")
        self.validation_label.setWordWrap(True)
        layout.addWidget(self.validation_label)

        buttons = QHBoxLayout()
        self.test_button = QPushButton("Kiểm tra mở GPT")
        self.test_button.setObjectName("testGptButton")
        self.open_inbox_button = QPushButton("Mở Inbox")
        self.open_inbox_button.setObjectName("settingsOpenInboxButton")
        self.save_button = QPushButton("Lưu cấu hình")
        self.save_button.setObjectName("saveSettingsButton")
        self.save_button.setProperty("primary", True)
        buttons.addWidget(self.test_button)
        buttons.addWidget(self.open_inbox_button)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        layout.addStretch(1)

    def _connect_signals(self) -> None:
        self.browse_executable_button.clicked.connect(self._browse_executable)
        self.browse_profile_button.clicked.connect(
            lambda: self._browse_directory(self.profile_edit, "Chọn thư mục browser profile")
        )
        self.browse_inbox_button.clicked.connect(
            lambda: self._browse_directory(self.inbox_edit, "Chọn thư mục nhận JSON")
        )
        self.detect_button.clicked.connect(self.detect_browser_requested)
        self.save_button.clicked.connect(self._request_save)
        self.test_button.clicked.connect(self._request_test)
        self.open_inbox_button.clicked.connect(
            lambda: self.open_inbox_requested.emit(Path(self.inbox_edit.text().strip()))
        )
        for widget_signal in (
            self.gpt_url_edit.textChanged,
            self.executable_edit.textChanged,
            self.profile_edit.textChanged,
            self.inbox_edit.textChanged,
            self.pattern_edit.textChanged,
            self.browser_combo.currentIndexChanged,
            self.stability_spin.valueChanged,
            self.max_size_spin.valueChanged,
            self.auto_open_check.toggled,
        ):
            widget_signal.connect(self._validate_form)

    def set_settings(self, settings: Any | None) -> None:
        self.gpt_url_edit.setText(
            str(_setting(settings, "gpt_url", "gpt_custom_url", "custom_gpt_url", default="") or "")
        )
        preference = str(
            _setting(
                settings,
                "browser_preference",
                "preferred_browser",
                "browser",
                default="auto",
            )
            or "auto"
        ).lower()
        index = self.browser_combo.findData(preference)
        self.browser_combo.setCurrentIndex(index if index >= 0 else 0)
        self.executable_edit.setText(
            str(
                _setting(
                    settings,
                    "browser_executable",
                    "browser_executable_path",
                    "executable_path",
                    default="",
                )
                or ""
            )
        )
        self.profile_edit.setText(
            str(
                _setting(
                    settings,
                    "browser_profile_dir",
                    "browser_profile_path",
                    "profile_dir",
                    default="",
                )
                or ""
            )
        )
        inbox = str(
            _setting(settings, "inbox_dir", "inbox_path", "inbox", default="") or ""
        )
        self.inbox_edit.setText(inbox)
        self._loaded_inbox = inbox
        self.pattern_edit.setText(
            str(
                _setting(
                    settings,
                    "file_pattern",
                    "filename_pattern",
                    "inbox_pattern",
                    default="ket_qua_boc_tach*.json",
                )
                or "ket_qua_boc_tach*.json"
            )
        )
        self.stability_spin.setValue(
            float(
                _setting(
                    settings,
                    "file_stability_seconds",
                    "stability_seconds",
                    "stable_seconds",
                    default=3.0,
                )
                or 3.0
            )
        )
        self.max_size_spin.setValue(
            int(_setting(settings, "max_file_size_mb", "max_size_mb", default=50) or 50)
        )
        self.auto_open_check.setChecked(
            bool(_setting(settings, "auto_open_review", default=True))
        )
        self._validate_form()

    def settings_data(self) -> dict[str, Any]:
        """Trả mapping thuần Python để ConfigManager/MainWindow ánh xạ sang AppSettings."""

        executable = self.executable_edit.text().strip()
        profile = self.profile_edit.text().strip()
        return {
            "gpt_url": self.gpt_url_edit.text().strip(),
            "browser_preference": str(self.browser_combo.currentData()),
            "browser_executable": executable or None,
            "browser_profile_dir": profile or None,
            "inbox_dir": self.inbox_edit.text().strip(),
            "file_pattern": self.pattern_edit.text().strip(),
            "stable_seconds": float(self.stability_spin.value()),
            "max_file_size_mb": int(self.max_size_spin.value()),
            "auto_open_review": self.auto_open_check.isChecked(),
        }

    values = settings_data

    def _validate_form(self, *_args: Any) -> bool:
        problems: list[str] = []
        url = self.gpt_url_edit.text().strip()
        parsed = urlparse(url)
        if url and (parsed.scheme not in {"http", "https"} or not parsed.netloc):
            problems.append("URL GPT phải là địa chỉ http/https hợp lệ.")
        if not self.inbox_edit.text().strip():
            problems.append("Cần chọn thư mục Inbox.")
        pattern = self.pattern_edit.text().strip()
        if not pattern:
            problems.append("Pattern tên file không được để trống.")
        elif not pattern.casefold().endswith(".json"):
            problems.append("Pattern nhận file phải kết thúc bằng .json.")

        self.gpt_url_edit.setProperty(
            "invalid",
            bool(url) and (parsed.scheme not in {"http", "https"} or not parsed.netloc),
        )
        self.inbox_edit.setProperty("invalid", not self.inbox_edit.text().strip())
        self.pattern_edit.setProperty(
            "invalid", not pattern or not pattern.casefold().endswith(".json")
        )
        for widget in (self.gpt_url_edit, self.inbox_edit, self.pattern_edit):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

        valid = not problems
        self.save_button.setEnabled(valid)
        self.test_button.setEnabled(
            bool(url) and parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        )
        self.open_inbox_button.setEnabled(bool(self.inbox_edit.text().strip()))
        if problems:
            self.validation_label.setText(" • ".join(problems))
            self.validation_label.setProperty("status", "error")
        else:
            changed = self.inbox_edit.text().strip() != self._loaded_inbox
            suffix = " Inbox mới sẽ được theo dõi ngay sau khi lưu." if changed else ""
            if not url:
                self.validation_label.setText(
                    "Có thể lưu cấu hình, nhưng cần nhập URL GPT trước khi mở trợ lý."
                    + suffix
                )
                self.validation_label.setProperty("status", "warning")
            else:
                self.validation_label.setText("Cấu hình hợp lệ." + suffix)
                self.validation_label.setProperty("status", "success")
        self.validation_label.style().unpolish(self.validation_label)
        self.validation_label.style().polish(self.validation_label)
        return valid

    def _request_save(self) -> None:
        if self._validate_form():
            self.save_requested.emit(self.settings_data())

    def _request_test(self) -> None:
        if self._validate_form():
            self.test_gpt_requested.emit(self.settings_data())

    def mark_saved(self, settings: Any | None = None) -> None:
        if settings is not None:
            self.set_settings(settings)
        self._loaded_inbox = self.inbox_edit.text().strip()
        self.validation_label.setText("Đã lưu cấu hình.")
        self.validation_label.setProperty("status", "success")
        self.validation_label.style().unpolish(self.validation_label)
        self.validation_label.style().polish(self.validation_label)

    def set_detected_browser(self, path: str | Path | None, browser: str | None = None) -> None:
        if not path:
            self.validation_label.setText(
                "Không tìm thấy Chrome/Edge. Bạn vẫn có thể dùng trình duyệt mặc định Windows."
            )
            self.validation_label.setProperty("status", "warning")
        else:
            self.executable_edit.setText(str(path))
            if browser:
                index = self.browser_combo.findData(browser.lower())
                if index >= 0:
                    self.browser_combo.setCurrentIndex(index)
            self.validation_label.setText(f"Đã tìm thấy trình duyệt: {path}")
            self.validation_label.setProperty("status", "success")
        self.validation_label.style().unpolish(self.validation_label)
        self.validation_label.style().polish(self.validation_label)

    def _browse_executable(self) -> None:
        start = self.executable_edit.text().strip()
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn executable Chrome hoặc Edge",
            start,
            "Chương trình Windows (*.exe);;Tất cả file (*)",
        )
        if filename:
            self.executable_edit.setText(filename)

    def _browse_directory(self, target: QLineEdit, title: str) -> None:
        start = target.text().strip()
        directory = QFileDialog.getExistingDirectory(self, title, start)
        if directory:
            target.setText(directory)

"""Trang xem phần cuối log kỹ thuật ở chế độ chỉ đọc."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class LogPage(QWidget):
    """Đọc tail log an toàn; thiếu file log không làm ứng dụng crash."""

    refresh_requested = Signal()
    open_file_requested = Signal(object)
    open_folder_requested = Signal(object)

    def __init__(
        self,
        log_path: str | Path | None = None,
        parent: QWidget | None = None,
        *,
        max_lines: int = 2000,
        max_bytes: int = 512 * 1024,
    ) -> None:
        super().__init__(parent)
        self._log_path = Path(log_path) if log_path else None
        self._max_lines = max(100, max_lines)
        self._max_bytes = max(16 * 1024, max_bytes)
        self._build_ui()
        self._connect_signals()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(10)
        title = QLabel("Nhật ký")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Hiển thị phần cuối log ứng dụng. Chi tiết này hữu ích khi cần chẩn đoán "
            "sự cố nhận hoặc lưu file."
        )
        subtitle.setProperty("muted", True)
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        controls = QHBoxLayout()
        self.path_label = QLabel("Chưa xác định file log")
        self.path_label.setObjectName("logPathLabel")
        self.path_label.setProperty("muted", True)
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        controls.addWidget(self.path_label, 1)
        self.refresh_button = QPushButton("Làm mới")
        self.refresh_button.setObjectName("refreshLogButton")
        self.open_file_button = QPushButton("Mở file log")
        self.open_file_button.setObjectName("openLogFileButton")
        self.open_folder_button = QPushButton("Mở thư mục log")
        self.open_folder_button.setObjectName("openLogFolderButton")
        controls.addWidget(self.refresh_button)
        controls.addWidget(self.open_file_button)
        controls.addWidget(self.open_folder_button)
        layout.addLayout(controls)

        self.viewer = QPlainTextEdit()
        self.viewer.setObjectName("logViewer")
        self.viewer.setReadOnly(True)
        self.viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.viewer.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.viewer.setPlaceholderText("Log sẽ xuất hiện sau khi ứng dụng ghi sự kiện đầu tiên.")
        layout.addWidget(self.viewer, 1)

        self.status_label = QLabel()
        self.status_label.setProperty("muted", True)
        layout.addWidget(self.status_label)

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self.refresh)
        self.open_file_button.clicked.connect(self.open_log_file)
        self.open_folder_button.clicked.connect(self.open_log_folder)

    @property
    def log_path(self) -> Path | None:
        return self._log_path

    def set_log_path(self, path: str | Path | None) -> None:
        self._log_path = Path(path) if path else None
        self.refresh()

    def refresh(self) -> None:
        self.refresh_requested.emit()
        path = self._log_path
        self.path_label.setText(str(path) if path else "Chưa xác định file log")
        if path is None:
            self.viewer.clear()
            self.status_label.setText("Ứng dụng chưa cung cấp đường dẫn log.")
            self.open_file_button.setEnabled(False)
            self.open_folder_button.setEnabled(False)
            return

        self.open_folder_button.setEnabled(path.parent.exists())
        if not path.exists():
            self.viewer.clear()
            self.status_label.setText(
                "File log chưa được tạo. Hãy làm mới sau khi ứng dụng phát sinh sự kiện."
            )
            self.open_file_button.setEnabled(False)
            return
        try:
            size = path.stat().st_size
            with path.open("rb") as stream:
                if size > self._max_bytes:
                    stream.seek(-self._max_bytes, 2)
                    stream.readline()
                content = stream.read().decode("utf-8", errors="replace")
            lines = content.splitlines()
            if len(lines) > self._max_lines:
                lines = lines[-self._max_lines :]
            self.viewer.setPlainText("\n".join(lines))
            self.viewer.moveCursor(QTextCursor.MoveOperation.End)
            self.open_file_button.setEnabled(True)
            self.status_label.setText(
                f"Đã nạp {len(lines):,} dòng cuối • {size:,} byte".replace(",", ".")
            )
        except OSError as exc:
            self.viewer.clear()
            self.open_file_button.setEnabled(False)
            self.status_label.setText(f"Không đọc được file log: {exc}")

    def open_log_file(self) -> None:
        path = self._log_path
        if path is None or not path.exists():
            QMessageBox.information(
                self,
                "File log chưa tồn tại",
                "Chưa có file log để mở. Hãy làm mới sau khi ứng dụng ghi sự kiện.",
            )
            return
        self.open_file_requested.emit(path)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(self, "Không mở được file", f"Không thể mở:\n{path}")

    def open_log_folder(self) -> None:
        path = self._log_path
        folder = path.parent if path else None
        if folder is None or not folder.exists():
            QMessageBox.information(
                self,
                "Thư mục log chưa tồn tại",
                "Ứng dụng chưa tạo thư mục log.",
            )
            return
        self.open_folder_requested.emit(folder)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            QMessageBox.warning(self, "Không mở được thư mục", f"Không thể mở:\n{folder}")


# Alias theo cách gọi tiếng Anh đầy đủ.
LogsPage = LogPage

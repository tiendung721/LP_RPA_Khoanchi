"""Trang Quy trình với hai bước hoạt động và hai bước mở rộng bị vô hiệu."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


def _get(source: Any, *names: str, default: Any = None) -> Any:
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


def _display_time(value: Any) -> str:
    if not value:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M:%S")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime(
            "%d/%m/%Y %H:%M:%S"
        )
    except ValueError:
        return str(value)


def _status_text(value: Any) -> str:
    code = str(value or "RECEIVED").split(".")[-1].upper()
    return {
        "RECEIVED": "Đã tiếp nhận",
        "REVIEWING": "Đang kiểm tra",
        "READY": "Đã xác nhận",
        "INVALID": "Không hợp lệ",
        "ARCHIVED": "Đã lưu trữ",
    }.get(code, code)


class WorkflowPage(QWidget):
    """Trang điều phối thao tác hàng ngày; logic nghiệp vụ được phát qua signal."""

    open_gpt_requested = Signal()
    open_inbox_requested = Signal()
    choose_json_requested = Signal()
    open_review_requested = Signal(object)
    reload_requested = Signal(object)

    def __init__(
        self,
        settings: Any | None = None,
        active_batch: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._batch: Any | None = None
        self._gpt_url_valid = False
        self._build_ui()
        self._connect_signals()
        self.set_configuration(settings)
        self.set_active_batch(active_batch)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 26)
        layout.setSpacing(14)
        scroll.setWidget(body)

        title = QLabel("Quy trình")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Mở GPT Custom, nhận file JSON và hoàn tất kiểm tra dữ liệu trước khi "
            "chuyển sang các giai đoạn sau."
        )
        subtitle.setProperty("muted", True)
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.step1_card = QFrame()
        self.step1_card.setProperty("card", True)
        step1 = QVBoxLayout(self.step1_card)
        step1.setContentsMargins(18, 15, 18, 16)
        step1.setSpacing(9)
        header1 = QHBoxLayout()
        name1 = QLabel("Bước 1 – Mở trợ lý GPT")
        name1.setStyleSheet("font-size: 13pt; font-weight: 700;")
        self.gpt_config_status = QLabel()
        header1.addWidget(name1)
        header1.addStretch()
        header1.addWidget(self.gpt_config_status)
        step1.addLayout(header1)
        guide = QLabel(
            "Trong trình duyệt, gửi chứng từ cho GPT rồi tải "
            "<b>ket_qua_boc_tach.json</b> vào thư mục nhận file bên dưới."
        )
        guide.setWordWrap(True)
        step1.addWidget(guide)
        path_title = QLabel("Thư mục Inbox hiện tại")
        path_title.setProperty("muted", True)
        self.inbox_path_label = QLabel("—")
        self.inbox_path_label.setObjectName("inboxPathLabel")
        self.inbox_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.inbox_path_label.setWordWrap(True)
        step1.addWidget(path_title)
        step1.addWidget(self.inbox_path_label)
        actions1 = QHBoxLayout()
        self.open_gpt_button = QPushButton("Mở trợ lý GPT")
        self.open_gpt_button.setObjectName("openGptButton")
        self.open_gpt_button.setProperty("primary", True)
        self.open_inbox_button = QPushButton("Mở thư mục nhận file")
        self.open_inbox_button.setObjectName("openInboxButton")
        self.choose_file_button = QPushButton("Chọn file JSON thủ công")
        self.choose_file_button.setObjectName("chooseJsonButton")
        actions1.addWidget(self.open_gpt_button)
        actions1.addWidget(self.open_inbox_button)
        actions1.addWidget(self.choose_file_button)
        actions1.addStretch()
        step1.addLayout(actions1)
        layout.addWidget(self.step1_card)

        self.step2_card = QFrame()
        self.step2_card.setProperty("card", True)
        step2 = QVBoxLayout(self.step2_card)
        step2.setContentsMargins(18, 15, 18, 16)
        step2.setSpacing(10)
        header2 = QHBoxLayout()
        name2 = QLabel("Bước 2 – Kiểm tra dữ liệu bóc tách")
        name2.setStyleSheet("font-size: 13pt; font-weight: 700;")
        self.batch_status_badge = QLabel("Chưa có dữ liệu")
        header2.addWidget(name2)
        header2.addStretch()
        header2.addWidget(self.batch_status_badge)
        step2.addLayout(header2)

        self.no_batch_label = QLabel(
            "Chưa có batch đang hoạt động. Ứng dụng sẽ cập nhật khi nhận được JSON "
            "từ Inbox hoặc khi bạn chọn file thủ công."
        )
        self.no_batch_label.setWordWrap(True)
        self.no_batch_label.setProperty("muted", True)
        step2.addWidget(self.no_batch_label)

        self.batch_details = QWidget()
        grid = QGridLayout(self.batch_details)
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(8)
        self.batch_filename = QLabel("—")
        self.received_at = QLabel("—")
        self.saved_at = QLabel("—")
        self.row_count = QLabel("0")
        self.warning_count = QLabel("0")
        self.error_count = QLabel("0")
        detail_items = (
            ("Tên file / batch", self.batch_filename),
            ("Thời điểm nhận", self.received_at),
            ("Lưu gần nhất", self.saved_at),
            ("Số dòng", self.row_count),
            ("Cảnh báo", self.warning_count),
            ("Lỗi", self.error_count),
        )
        for index, (caption, value) in enumerate(detail_items):
            row, column_group = divmod(index, 3)
            column = column_group * 2
            caption_label = QLabel(caption)
            caption_label.setProperty("muted", True)
            value.setStyleSheet("font-weight: 600;")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(caption_label, row, column)
            grid.addWidget(value, row, column + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(5, 1)
        step2.addWidget(self.batch_details)
        actions2 = QHBoxLayout()
        self.review_button = QPushButton("Xem và chỉnh sửa dữ liệu")
        self.review_button.setObjectName("openReviewButton")
        self.review_button.setProperty("primary", True)
        self.reload_button = QPushButton("Tải lại từ bản làm việc")
        self.reload_button.setObjectName("reloadWorkingButton")
        actions2.addWidget(self.review_button)
        actions2.addWidget(self.reload_button)
        actions2.addStretch()
        step2.addLayout(actions2)
        layout.addWidget(self.step2_card)

        upcoming = QHBoxLayout()
        upcoming.setSpacing(14)
        step3 = self._upcoming_card(
            "Bước 3 – Nhập dữ liệu vào Excel",
            "Sẽ phát triển sau",
            "Giai đoạn này chưa triển khai trong phiên bản hiện tại.",
        )
        step4 = self._upcoming_card(
            "Bước 4 – Chạy RPA PAD",
            "Sẽ phát triển sau",
            "Không có tác vụ Power Automate Desktop nào được chạy ở phiên bản này.",
        )
        upcoming.addWidget(step3, 1)
        upcoming.addWidget(step4, 1)
        layout.addLayout(upcoming)
        layout.addStretch(1)

    @staticmethod
    def _upcoming_card(title: str, badge: str, description: str) -> QFrame:
        card = QFrame()
        card.setProperty("upcoming", True)
        card.setEnabled(False)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 18, 14)
        header = QHBoxLayout()
        name = QLabel(title)
        name.setStyleSheet("font-size: 12pt; font-weight: 700; color: #64748B;")
        status = QLabel(badge)
        status.setStyleSheet(
            "color: #64748B; background: #E2E8F0; border-radius: 5px; padding: 4px 8px;"
        )
        header.addWidget(name)
        header.addStretch()
        header.addWidget(status)
        box.addLayout(header)
        text = QLabel(description)
        text.setWordWrap(True)
        text.setStyleSheet("color: #7B8798;")
        box.addWidget(text)
        return card

    def _connect_signals(self) -> None:
        self.open_gpt_button.clicked.connect(self.open_gpt_requested)
        self.open_inbox_button.clicked.connect(self.open_inbox_requested)
        self.choose_file_button.clicked.connect(self.choose_json_requested)
        self.review_button.clicked.connect(
            lambda: self.open_review_requested.emit(self._batch)
        )
        self.reload_button.clicked.connect(lambda: self.reload_requested.emit(self._batch))

    def set_configuration(self, settings: Any | None) -> None:
        self._settings = settings
        url = str(
            _get(settings, "gpt_url", "gpt_custom_url", "custom_gpt_url", default="") or ""
        ).strip()
        inbox = str(
            _get(settings, "inbox_dir", "inbox_path", "inbox", default="") or ""
        ).strip()
        valid_url = urlparse(url).scheme in {"http", "https"} and bool(urlparse(url).netloc)
        self._gpt_url_valid = valid_url
        if valid_url:
            self.gpt_config_status.setText("Đã cấu hình URL")
            self.gpt_config_status.setStyleSheet(
                "color: #15803D; background: #ECFDF3; border-radius: 5px; padding: 4px 8px;"
            )
        else:
            self.gpt_config_status.setText("Chưa cấu hình URL hợp lệ")
            self.gpt_config_status.setStyleSheet(
                "color: #A16207; background: #FFF8DB; border-radius: 5px; padding: 4px 8px;"
            )
        self.open_gpt_button.setEnabled(valid_url)
        self.inbox_path_label.setText(inbox or "Chưa cấu hình thư mục Inbox")
        self.inbox_path_label.setToolTip(inbox)
        self.open_inbox_button.setEnabled(bool(inbox))

    def set_active_batch(self, batch: Any | None) -> None:
        self._batch = batch
        metadata = _get(batch, "metadata", default=batch)
        has_batch = metadata is not None and _get(metadata, "id", "batch_id") is not None
        self.no_batch_label.setVisible(not has_batch)
        self.batch_details.setVisible(has_batch)
        if not has_batch:
            self.batch_status_badge.setText("Chưa có dữ liệu")
            self.batch_status_badge.setStyleSheet(
                "color: #64748B; background: #E2E8F0; border-radius: 5px; padding: 4px 8px;"
            )
            self.review_button.setEnabled(False)
            self.reload_button.setEnabled(False)
            return

        status_code = str(_get(metadata, "status", default="RECEIVED")).split(".")[-1].upper()
        filename = str(
            _get(metadata, "source_filename", "filename", "file_name", default="—")
        )
        batch_id = _get(metadata, "id", "batch_id")
        self.batch_filename.setText(f"#{batch_id} – {filename}")
        self.batch_filename.setToolTip(filename)
        self.received_at.setText(_display_time(_get(metadata, "received_at", "created_at")))
        self.saved_at.setText(_display_time(_get(metadata, "last_saved_at", "saved_at")))

        validation = _get(batch, "validation")
        summary = _get(validation, "summary")
        self.row_count.setText(
            str(_get(summary, "total_rows", "total", default=_get(metadata, "row_count", default=0)))
        )
        self.warning_count.setText(
            str(
                _get(
                    summary,
                    "warning_count",
                    "warning",
                    default=_get(metadata, "warning_count", default=0),
                )
            )
        )
        self.error_count.setText(
            str(
                _get(
                    summary,
                    "error_count",
                    "error",
                    default=_get(metadata, "error_count", default=0),
                )
            )
        )
        self.batch_status_badge.setText(_status_text(status_code))
        if status_code == "INVALID":
            color, background = "#B42318", "#FFF0F0"
        elif status_code == "READY":
            color, background = "#15803D", "#ECFDF3"
        else:
            color, background = "#1D4ED8", "#EFF6FF"
        self.batch_status_badge.setStyleSheet(
            f"color: {color}; background: {background}; border-radius: 5px; "
            "padding: 4px 8px; font-weight: 600;"
        )
        usable = status_code != "INVALID"
        self.review_button.setEnabled(usable)
        self.reload_button.setEnabled(usable and bool(_get(metadata, "working_path", default=True)))

    def clear_active_batch(self) -> None:
        self.set_active_batch(None)

    @property
    def active_batch(self) -> Any | None:
        return self._batch

    def set_busy(self, busy: bool, message: str | None = None) -> None:
        self.open_gpt_button.setEnabled(not busy and self._gpt_url_valid)
        self.choose_file_button.setEnabled(not busy)
        if message:
            self.gpt_config_status.setText(message)

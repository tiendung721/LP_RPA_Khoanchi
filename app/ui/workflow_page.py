"""Trang Quy trình cho luồng Trợ lý ảo -> Output -> kiểm tra JSON -> Excel."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
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


def _saved_text(value: Any) -> str:
    if not value:
        return "—"
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return str(value)
    return parsed.strftime("%H:%M ngày %d/%m/%Y")


class WorkflowPage(QWidget):
    open_assistant_requested = Signal()
    open_review_requested = Signal(object)
    sync_daily_requested = Signal()
    post_expenses_requested = Signal()
    sync_payment_requested = Signal()

    SYNC_OPERATION = "sync"
    POSTING_OPERATION = "posting"
    PAYMENT_SYNC_OPERATION = "payment_sync"

    def __init__(
        self,
        settings: Any | None = None,
        active_batch: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._batch: Any | None = None
        self._build_ui()
        self.open_assistant_button.clicked.connect(self.open_assistant_requested)
        self.review_button.clicked.connect(
            lambda: self.open_review_requested.emit(self._batch)
        )
        self.sync_daily_button.clicked.connect(self.sync_daily_requested)
        self.post_expenses_button.clicked.connect(self.post_expenses_requested)
        self.sync_payment_button.clicked.connect(self.sync_payment_requested)
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
            "Mở Trợ lý ảo, tải file kết quả và kiểm tra dữ liệu bóc tách."
        )
        subtitle.setProperty("muted", True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.step1_card = QFrame()
        self.step1_card.setProperty("card", True)
        step1 = QVBoxLayout(self.step1_card)
        step1.setContentsMargins(18, 15, 18, 16)
        step1.setSpacing(10)
        header1 = QHBoxLayout()
        name1 = QLabel("Bước 1 – Mở Trợ lý ảo")
        name1.setStyleSheet("font-size: 13pt; font-weight: 700;")
        self.assistant_status = QLabel()
        header1.addWidget(name1)
        header1.addStretch()
        header1.addWidget(self.assistant_status)
        step1.addLayout(header1)
        guide = QLabel(
            "Gửi chứng từ cho Trợ lý ảo và tải file kết quả. "
            "Phần mềm sẽ tự nhận file mới."
        )
        guide.setWordWrap(True)
        step1.addWidget(guide)
        actions1 = QHBoxLayout()
        self.open_assistant_button = QPushButton("Mở Trợ lý ảo")
        self.open_assistant_button.setObjectName("openAssistantButton")
        self.open_assistant_button.setProperty("primary", True)
        actions1.addWidget(self.open_assistant_button)
        actions1.addStretch()
        step1.addLayout(actions1)
        layout.addWidget(self.step1_card)

        self.step2_card = QFrame()
        self.step2_card.setProperty("card", True)
        step2 = QVBoxLayout(self.step2_card)
        step2.setContentsMargins(18, 15, 18, 16)
        step2.setSpacing(10)
        header2 = QHBoxLayout()
        name2 = QLabel("Bước 2 – Xem file bóc tách dữ liệu")
        name2.setStyleSheet("font-size: 13pt; font-weight: 700;")
        self.file_status_badge = QLabel()
        header2.addWidget(name2)
        header2.addStretch()
        header2.addWidget(self.file_status_badge)
        step2.addLayout(header2)

        self.file_name_label = QLabel("Chưa có file bóc tách")
        self.file_name_label.setObjectName("fileNameLabel")
        self.file_name_label.setStyleSheet("font-size: 12pt; font-weight: 600;")
        self.file_name_label.setWordWrap(True)
        self.file_note_label = QLabel("Chưa nhận được file bóc tách dữ liệu.")
        self.file_note_label.setWordWrap(True)
        self.file_note_label.setProperty("muted", True)
        self.saved_label = QLabel("Lưu thành công lần cuối: —")
        self.saved_label.setProperty("muted", True)
        step2.addWidget(self.file_name_label)
        step2.addWidget(self.file_note_label)
        step2.addWidget(self.saved_label)

        actions2 = QHBoxLayout()
        actions2.addStretch()
        self.review_button = QPushButton("Xem file bóc tách")
        self.review_button.setObjectName("openReviewButton")
        self.review_button.setProperty("primary", True)
        actions2.addWidget(self.review_button)
        step2.addLayout(actions2)
        layout.addWidget(self.step2_card)

        self.step3_card = QFrame()
        self.step3_card.setObjectName("excelWorkflowCard")
        self.step3_card.setProperty("card", True)
        step3 = QVBoxLayout(self.step3_card)
        step3.setContentsMargins(18, 15, 18, 16)
        step3.setSpacing(10)

        name3 = QLabel("Bước 3 – Xử lý dữ liệu Excel")
        name3.setStyleSheet("font-size: 13pt; font-weight: 700;")
        step3.addWidget(name3)

        guide3 = QLabel(
            "Đồng bộ dữ liệu từ file Hàng ngày hoặc nhập các khoản chi đã xác nhận "
            "vào file BK Tổng hợp."
        )
        guide3.setWordWrap(True)
        guide3.setProperty("muted", True)
        step3.addWidget(guide3)

        self.sync_status_label = QLabel("Đồng bộ gần nhất: —")
        self.sync_status_label.setObjectName("dailySyncStatusLabel")
        self.sync_status_label.setWordWrap(True)
        self.sync_status_label.setProperty("muted", True)
        self.posting_status_label = QLabel("Nhập khoản chi gần nhất: —")
        self.posting_status_label.setObjectName("expensePostingStatusLabel")
        self.posting_status_label.setWordWrap(True)
        self.posting_status_label.setProperty("muted", True)
        self.payment_sync_status_label = QLabel(
            "Đồng bộ BK → Thanh toán gần nhất: —"
        )
        self.payment_sync_status_label.setObjectName("paymentSyncStatusLabel")
        self.payment_sync_status_label.setWordWrap(True)
        self.payment_sync_status_label.setProperty("muted", True)
        actions3 = QHBoxLayout()
        self.sync_daily_button = QPushButton("Đồng bộ dữ liệu Hàng ngày")
        self.sync_daily_button.setObjectName("syncDailyWorkbookButton")
        self.sync_daily_button.setProperty("primary", True)
        self.post_expenses_button = QPushButton("Nhập khoản chi vào BK")
        self.post_expenses_button.setObjectName("postExpensesWorkbookButton")
        self.post_expenses_button.setProperty("primary", True)
        self.sync_payment_button = QPushButton("Đồng bộ BK → Thanh toán")
        self.sync_payment_button.setObjectName("syncPaymentWorkbookButton")
        self.sync_payment_button.setProperty("primary", True)
        actions3.addWidget(self.sync_daily_button)
        actions3.addWidget(self.post_expenses_button)
        actions3.addWidget(self.sync_payment_button)
        actions3.addStretch()
        step3.addLayout(actions3)
        step3.addWidget(self.sync_status_label)
        step3.addWidget(self.posting_status_label)
        step3.addWidget(self.payment_sync_status_label)
        layout.addWidget(self.step3_card)

        # Aliases có chủ ý để lớp điều phối có thể dùng cách đặt tên theo nghiệp vụ
        # mà không tạo thêm widget/nút chính.
        self.daily_sync_button = self.sync_daily_button
        self.expense_posting_button = self.post_expenses_button
        self.daily_sync_status_label = self.sync_status_label
        self.expense_posting_status_label = self.posting_status_label
        self._excel_running_operation: str | None = None
        self._excel_button_texts = {
            self.SYNC_OPERATION: self.sync_daily_button.text(),
            self.POSTING_OPERATION: self.post_expenses_button.text(),
            self.PAYMENT_SYNC_OPERATION: self.sync_payment_button.text(),
        }
        layout.addStretch(1)

    def set_configuration(self, settings: Any | None) -> None:
        self._settings = settings
        bat = str(_get(settings, "assistant_bat_path", default="") or "").strip()
        if bat:
            self.assistant_status.setText("Đã cấu hình")
            self.assistant_status.setStyleSheet(
                "color: #15803D; background: #ECFDF3; border-radius: 5px; "
                "padding: 4px 8px;"
            )
        else:
            self.assistant_status.setText("Chưa cấu hình BAT")
            self.assistant_status.setStyleSheet(
                "color: #A16207; background: #FFF8DB; border-radius: 5px; "
                "padding: 4px 8px;"
            )

    def set_active_batch(self, batch: Any | None) -> None:
        self._batch = batch
        metadata = _get(batch, "metadata", default=batch)
        has_batch = metadata is not None and _get(metadata, "id", "batch_id") is not None
        if not has_batch:
            self.file_status_badge.setText("Chưa có file")
            self.file_status_badge.setStyleSheet(
                "color: #64748B; background: #E2E8F0; border-radius: 5px; "
                "padding: 4px 8px;"
            )
            self.file_name_label.setText("Chưa có file bóc tách")
            self.file_note_label.setText("Chưa nhận được file bóc tách dữ liệu.")
            self.saved_label.setText("Lưu thành công lần cuối: —")
            self.review_button.setEnabled(False)
            return

        filename = str(
            _get(metadata, "source_filename", "filename", default="ket_qua_boc_tach.json")
        )
        status = str(_get(metadata, "status", default="RECEIVED")).split(".")[-1].upper()
        invalid = status == "INVALID"
        self.file_name_label.setText(filename)
        self.file_name_label.setToolTip(filename)
        if invalid:
            self.file_status_badge.setText("File không hợp lệ")
            self.file_status_badge.setStyleSheet(
                "color: #B42318; background: #FFF0F0; border-radius: 5px; "
                "padding: 4px 8px; font-weight: 600;"
            )
            self.file_note_label.setText(
                str(_get(metadata, "last_error", default="File JSON không hợp lệ."))
            )
            self.saved_label.setText("Lưu thành công lần cuối: —")
            self.review_button.setEnabled(False)
            return

        self.file_status_badge.setText("Đã có file")
        self.file_status_badge.setStyleSheet(
            "color: #15803D; background: #ECFDF3; border-radius: 5px; "
            "padding: 4px 8px; font-weight: 600;"
        )
        saved_at = _get(metadata, "last_saved_at", "saved_at")
        self.file_note_label.setText(
            "Đã lưu dữ liệu bóc tách JSON sau khi kiểm tra."
            if saved_at
            else "Đã nhận file mới; hãy kiểm tra và lưu dữ liệu."
        )
        self.saved_label.setText(
            f"Lưu thành công lần cuối: {_saved_text(saved_at)}"
        )
        self.review_button.setEnabled(True)

    def clear_active_batch(self) -> None:
        self.set_active_batch(None)

    @staticmethod
    def _excel_operation(operation: Any) -> str:
        value = str(getattr(operation, "value", operation) or "").casefold()
        if value in {"sync", "daily_sync", "sync_daily", "daily"}:
            return WorkflowPage.SYNC_OPERATION
        if value in {
            "posting",
            "post",
            "expense_posting",
            "post_expenses",
            "expenses",
        }:
            return WorkflowPage.POSTING_OPERATION
        if value in {
            "payment_sync",
            "sync_payment",
            "bk_to_payment",
            "payment",
        }:
            return WorkflowPage.PAYMENT_SYNC_OPERATION
        raise ValueError(f"Nghiệp vụ Excel không hợp lệ: {operation!r}")

    def set_excel_running(self, operation: Any, message: str = "") -> None:
        """Hiển thị tiến độ và khóa đồng thời cả hai thao tác Excel."""

        normalized = self._excel_operation(operation)
        self._excel_running_operation = normalized
        self.sync_daily_button.setEnabled(False)
        self.post_expenses_button.setEnabled(False)
        self.sync_payment_button.setEnabled(False)
        if normalized == self.SYNC_OPERATION:
            self.sync_daily_button.setText("Đang đồng bộ…")
            self.sync_status_label.setText(
                f"Đồng bộ: {message or 'Đang phân tích dữ liệu…'}"
            )
        elif normalized == self.POSTING_OPERATION:
            self.post_expenses_button.setText("Đang nhập…")
            self.posting_status_label.setText(
                f"Nhập khoản chi: {message or 'Đang phân tích dữ liệu…'}"
            )
        else:
            self.sync_payment_button.setText("Đang đồng bộ…")
            self.payment_sync_status_label.setText(
                "Đồng bộ BK → Thanh toán: "
                f"{message or 'Đang phân tích dữ liệu…'}"
            )

    def set_excel_progress(self, operation: Any, message: str) -> None:
        normalized = self._excel_operation(operation)
        if normalized == self.SYNC_OPERATION:
            self.sync_status_label.setText(f"Đồng bộ: {message}")
        elif normalized == self.POSTING_OPERATION:
            self.posting_status_label.setText(f"Nhập khoản chi: {message}")
        else:
            self.payment_sync_status_label.setText(
                f"Đồng bộ BK → Thanh toán: {message}"
            )

    def set_excel_result(self, operation: Any, result: Any = None) -> None:
        """Cập nhật kết quả gần nhất từ dataclass, mapping hoặc chuỗi."""

        normalized = self._excel_operation(operation)
        if isinstance(result, str):
            message = result
        else:
            message = str(
                _get(result, "message", "summary", default="Hoàn tất.") or "Hoàn tất."
            )
        if normalized == self.SYNC_OPERATION:
            self.sync_status_label.setText(f"Đồng bộ gần nhất: {message}")
        elif normalized == self.POSTING_OPERATION:
            self.posting_status_label.setText(
                f"Nhập khoản chi gần nhất: {message}"
            )
        else:
            self.payment_sync_status_label.setText(
                f"Đồng bộ BK → Thanh toán gần nhất: {message}"
            )

    def set_excel_idle(self, operation: Any | None = None) -> None:
        """Khôi phục hai nút sau khi controller phát ``finished``."""

        if operation is not None:
            self._excel_operation(operation)
        self._excel_running_operation = None
        self.sync_daily_button.setText(
            self._excel_button_texts[self.SYNC_OPERATION]
        )
        self.post_expenses_button.setText(
            self._excel_button_texts[self.POSTING_OPERATION]
        )
        self.sync_payment_button.setText(
            self._excel_button_texts[self.PAYMENT_SYNC_OPERATION]
        )
        self.sync_daily_button.setEnabled(True)
        self.post_expenses_button.setEnabled(True)
        self.sync_payment_button.setEnabled(True)

    def set_excel_actions_enabled(self, enabled: bool) -> None:
        if self._excel_running_operation is not None and enabled:
            return
        self.sync_daily_button.setEnabled(enabled)
        self.post_expenses_button.setEnabled(enabled)
        self.sync_payment_button.setEnabled(enabled)

    @property
    def excel_running_operation(self) -> str | None:
        return self._excel_running_operation

    @property
    def active_batch(self) -> Any | None:
        return self._batch

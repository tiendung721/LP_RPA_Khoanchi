"""Popup xem trước container và số tiền trước khi thay dòng."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.container_load.contracts import ContainerAllocation


class ContainerLoadPreviewDialog(QDialog):
    def __init__(
        self,
        *,
        bl: str,
        source_path: str | Path,
        original_amount: object,
        allocations: Sequence[ContainerAllocation],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Xác nhận Load số container")
        self.resize(560, 420)
        self.allocations = tuple(allocations)
        self.can_confirm = bool(self.allocations) and all(
            item.amount is not None for item in self.allocations
        )

        layout = QVBoxLayout(self)
        title = QLabel(f"B/L: {bl}")
        title.setObjectName("containerLoadBlLabel")
        source = QLabel(f"File kết quả: {Path(source_path).name}")
        source.setProperty("muted", True)
        layout.addWidget(title)
        layout.addWidget(source)

        table = QTableWidget(len(self.allocations), 2)
        table.setObjectName("containerLoadPreviewTable")
        table.setHorizontalHeaderLabels(("Số container", "Số tiền (VND)"))
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        for row, allocation in enumerate(self.allocations):
            container_item = QTableWidgetItem(allocation.container)
            amount_item = QTableWidgetItem(
                "Không hợp lệ"
                if allocation.amount is None
                else f"{allocation.amount:,}".replace(",", ".")
            )
            amount_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            table.setItem(row, 0, container_item)
            table.setItem(row, 1, amount_item)
        layout.addWidget(table, 1)

        if self.can_confirm:
            allocated_total = sum(
                int(item.amount) for item in self.allocations if item.amount is not None
            )
            summary_text = (
                f"Tổng trước phân bổ: {int(original_amount):,} VND · "
                f"Tổng sau phân bổ: {allocated_total:,} VND"
            ).replace(",", ".")
        else:
            summary_text = (
                "Không thể xác nhận vì số tiền dòng gốc không phải "
                "số nguyên không âm. Hãy sửa dòng rồi Load lại."
            )
        summary = QLabel(summary_text)
        summary.setObjectName("containerLoadSummaryLabel")
        summary.setWordWrap(True)
        summary.setProperty("status", "success" if self.can_confirm else "error")
        layout.addWidget(summary)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        confirm = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        confirm.setText("Xác nhận")
        cancel.setText("Hủy")
        confirm.setEnabled(self.can_confirm)
        confirm.setProperty("primary", True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


__all__ = ["ContainerLoadPreviewDialog"]

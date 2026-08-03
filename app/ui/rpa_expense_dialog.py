"""Hộp thoại xem và chọn SQT trước khi gọi PAD."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


def _money(value: Any) -> str:
    try:
        return f"{int(value or 0):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(value or 0)


class RpaSqtSelectionDialog(QDialog):
    COLUMNS = (
        "Chọn",
        "SQT",
        "Trạng thái RPA",
        "Dòng BK",
        "Cước MB",
        "N.hạ MB",
        "Cước biển",
        "N.hạ/VS/D/O/Lệnh",
        "Cước MN",
        "Lưu cont/Quá tải",
        "Sửa chữa",
        "Tổng",
        "Kiểm tra",
    )

    def __init__(
        self,
        plan: Any,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.plan = plan
        self._checks: list[QTableWidgetItem] = []
        self.setObjectName("rpaSqtSelectionDialog")
        self.setWindowTitle("Chọn số quyết toán chạy RPA")
        self.resize(1380, 650)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        title = QLabel(
            f"Sheet {self.plan.sheet_name}: chọn các SQT cần nhập lên phần mềm quyết toán."
        )
        title.setStyleSheet("font-size: 12pt; font-weight: 700;")
        title.setWordWrap(True)
        layout.addWidget(title)
        note = QLabel(
            "SQT “Đã nhập” vẫn được phép chọn và chạy lại. "
            "Trạng thái chỉ được đổi sang “Đã nhập” sau khi PAD xác nhận đã lưu thành công trên web."
        )
        note.setWordWrap(True)
        note.setProperty("muted", True)
        layout.addWidget(note)

        selection = QHBoxLayout()
        select_all = QPushButton("Chọn tất cả hợp lệ")
        clear_all = QPushButton("Bỏ chọn tất cả")
        select_all.setObjectName("selectAllRpaSqtButton")
        clear_all.setObjectName("clearAllRpaSqtButton")
        select_all.clicked.connect(
            lambda: self._set_all(Qt.CheckState.Checked)
        )
        clear_all.clicked.connect(
            lambda: self._set_all(Qt.CheckState.Unchecked)
        )
        selection.addWidget(select_all)
        selection.addWidget(clear_all)
        selection.addStretch()
        layout.addLayout(selection)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setObjectName("rpaSqtTable")
        self.table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            12, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.table, 1)

        for item in self.plan.items:
            self._add_item(item)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setObjectName("rpaSqtDialogButtons")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Chạy RPA các SQT đã chọn"
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_item(self, source: Any) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        check = QTableWidgetItem()
        flags = Qt.ItemFlag.ItemIsSelectable
        if source.can_run:
            flags |= Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
            check.setCheckState(Qt.CheckState.Unchecked)
        check.setFlags(flags)
        check.setData(Qt.ItemDataRole.UserRole, source.sqt)
        self._checks.append(check)
        self.table.setItem(row, 0, check)

        amounts = source.amounts
        values = (
            source.sqt,
            source.status,
            ", ".join(str(value) for value in source.source_rows),
            _money(amounts.cuoc_bo_dong_hang),
            _money(amounts.nang_ha_dong_hang),
            _money(amounts.cuoc_bien),
            _money(amounts.nang_do_vs_lam_lenh),
            _money(amounts.cuoc_bo_tra_hang),
            _money(amounts.luu_cont_qua_tai),
            _money(amounts.sua_chua_cont),
            _money(amounts.total),
            source.validation_message or "Hợp lệ",
        )
        for column, value in enumerate(values, 1):
            cell = QTableWidgetItem(str(value))
            cell.setToolTip(str(value))
            if not source.can_run:
                cell.setForeground(QColor("#8A3B32"))
            self.table.setItem(row, column, cell)

    def _set_all(self, state: Qt.CheckState) -> None:
        for item in self._checks:
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(state)

    @property
    def selected_sqt(self) -> list[str]:
        return [
            str(item.data(Qt.ItemDataRole.UserRole))
            for item in self._checks
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable
            and item.checkState() == Qt.CheckState.Checked
        ]

    def _validate_and_accept(self) -> None:
        if not self.selected_sqt:
            QMessageBox.warning(
                self,
                "Chưa chọn SQT",
                "Vui lòng chọn ít nhất một SQT hợp lệ để chạy RPA.",
            )
            return
        self.accept()


__all__ = ["RpaSqtSelectionDialog"]

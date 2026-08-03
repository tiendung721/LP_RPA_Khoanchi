"""Trang lịch sử batch với bảng, tìm kiếm và thao tác mở an toàn."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


def _field(source: Any, *names: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        for name in names:
            if name in source:
                return source[name]
        return default
    for name in names:
        if hasattr(source, name):
            result = getattr(source, name)
            return result.value if hasattr(result, "value") else result
    return default


def _datetime_text(value: Any) -> str:
    if not value:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M:%S")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime(
            "%d/%m/%Y %H:%M:%S"
        )
    except (ValueError, TypeError):
        return str(value)


def _status_vi(value: Any) -> str:
    code = str(value or "").split(".")[-1].upper()
    return {
        "RECEIVED": "Đã tiếp nhận",
        "REVIEWING": "Đang kiểm tra",
        "READY": "Đã xác nhận",
        "INVALID": "Không hợp lệ",
        "ARCHIVED": "Đã lưu trữ",
    }.get(code, code or "—")


class BatchHistoryModel(QAbstractTableModel):
    """Model chỉ đọc cho metadata; không chứa thao tác xóa."""

    HEADERS: Final[tuple[str, ...]] = (
        "ID",
        "Tên file",
        "Thời điểm nhận",
        "Trạng thái",
        "Số dòng",
        "Cảnh báo",
        "Lỗi",
        "Tổng tiền (VND)",
        "Thời điểm xác nhận",
    )

    def __init__(self, batches: Iterable[Any] = (), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._batches = list(batches)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._batches)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation is Qt.Orientation.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return section + 1 if orientation is Qt.Orientation.Vertical else None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._batches):
            return None
        batch = self._batches[index.row()]
        raw = self._raw_value(batch, index.column())
        if role == Qt.ItemDataRole.UserRole:
            return raw
        if role == Qt.ItemDataRole.UserRole + 1:
            return batch
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() in (2, 8):
                return _datetime_text(raw)
            if index.column() == 3:
                return _status_vi(raw)
            if index.column() == 7:
                return f"{int(raw or 0):,}".replace(",", ".")
            return "—" if raw in (None, "") else raw
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in (0, 4, 5, 6, 7):
            alignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return int(alignment)
        if role == Qt.ItemDataRole.ToolTipRole:
            filename = _field(batch, "source_filename", "filename", default="")
            batch_id = _field(batch, "id", "batch_id", default="")
            return f"Batch #{batch_id}: {filename}"
        return None

    @staticmethod
    def _raw_value(batch: Any, column: int) -> Any:
        values = (
            _field(batch, "id", "batch_id"),
            _field(batch, "source_filename", "filename", "file_name"),
            _field(batch, "received_at", "created_at"),
            _field(batch, "status"),
            _field(batch, "row_count", default=0),
            _field(batch, "warning_count", default=0),
            _field(batch, "error_count", default=0),
            _field(batch, "total_amount", default=0),
            _field(batch, "confirmed_at"),
        )
        return values[column]

    def set_batches(self, batches: Iterable[Any]) -> None:
        self.beginResetModel()
        self._batches = list(batches)
        self.endResetModel()

    def batch_at(self, row: int) -> Any:
        return self._batches[row]


class BatchHistoryProxyModel(QSortFilterProxyModel):
    """Proxy tìm tên file và trạng thái tiếng Việt/mã trạng thái."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._query = ""
        self.setDynamicSortFilter(True)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_query(self, query: str) -> None:
        begin = getattr(self, "beginFilterChange", None)
        modern = callable(begin)
        if modern:
            begin()
        self._query = query.strip().casefold()
        if modern:
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self.invalidateFilter()

    def filterAcceptsRow(  # noqa: N802
        self, source_row: int, source_parent: QModelIndex
    ) -> bool:
        if not self._query:
            return True
        model = self.sourceModel()
        if model is None:
            return False
        filename = model.index(source_row, 1, source_parent).data(Qt.ItemDataRole.UserRole)
        status = model.index(source_row, 3, source_parent).data(Qt.ItemDataRole.UserRole)
        text = f"{filename or ''} {status or ''} {_status_vi(status)}".casefold()
        return self._query in text

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        first = left.data(Qt.ItemDataRole.UserRole)
        second = right.data(Qt.ItemDataRole.UserRole)
        if first is None:
            return False
        if second is None:
            return True
        if isinstance(first, (int, float)) and isinstance(second, (int, float)):
            return first < second
        return str(first).casefold() < str(second).casefold()


class HistoryPage(QWidget):
    """Danh sách lịch sử; mọi thao tác mở được chuyển cho MainWindow."""

    refresh_requested = Signal()
    open_batch_requested = Signal(object)
    open_path_requested = Signal(object)

    def __init__(self, batches: Iterable[Any] = (), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = BatchHistoryModel(batches, self)
        self.proxy_model = BatchHistoryProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        self._build_ui()
        self._connect_signals()
        self._update_count()
        self._update_actions()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(12)

        title = QLabel("Lịch sử")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Các batch đã tiếp nhận được giữ lại để xem và tiếp tục kiểm tra. "
            "Trang này không có chức năng xóa."
        )
        subtitle.setProperty("muted", True)
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        controls = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("historySearchEdit")
        self.search_edit.setPlaceholderText("Tìm theo tên file hoặc trạng thái…")
        self.search_edit.setClearButtonEnabled(True)
        controls.addWidget(self.search_edit, 1)
        self.count_label = QLabel()
        self.count_label.setProperty("muted", True)
        controls.addWidget(self.count_label)
        self.refresh_button = QPushButton("Làm mới")
        self.refresh_button.setObjectName("refreshHistoryButton")
        controls.addWidget(self.refresh_button)
        layout.addLayout(controls)

        table_card = QFrame()
        table_card.setProperty("card", True)
        card_layout = QVBoxLayout(table_card)
        card_layout.setContentsMargins(1, 1, 1, 1)
        self.table = QTableView()
        self.table.setObjectName("historyTable")
        self.table.setModel(self.proxy_model)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        card_layout.addWidget(self.table)
        layout.addWidget(table_card, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.open_batch_button = QPushButton("Mở batch")
        self.open_batch_button.setObjectName("openHistoryBatchButton")
        self.open_batch_button.setProperty("primary", True)
        self.open_batch_button.setMinimumWidth(130)

        self.path_button = QToolButton()
        self.path_button.setObjectName("openHistoryPathButton")
        self.path_button.setText("Mở thư mục chứa")
        self.path_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.path_button)
        self.current_file_action = QAction("File JSON hiện hành", self)
        menu.addAction(self.current_file_action)
        self.path_button.setMenu(menu)
        actions.addWidget(self.path_button)
        actions.addWidget(self.open_batch_button)
        layout.addLayout(actions)

    def _connect_signals(self) -> None:
        self.search_edit.textChanged.connect(self.proxy_model.set_query)
        self.search_edit.textChanged.connect(self._update_count)
        self.refresh_button.clicked.connect(self.refresh_requested)
        self.open_batch_button.clicked.connect(self._emit_open_batch)
        self.table.doubleClicked.connect(lambda _index: self._emit_open_batch())
        self.table.selectionModel().selectionChanged.connect(self._update_actions)
        self.current_file_action.triggered.connect(
            lambda: self._emit_open_path("source_output_path")
        )

    def set_batches(self, batches: Iterable[Any]) -> None:
        self.model.set_batches(batches)
        self.table.clearSelection()
        self._update_count()
        self._update_actions()

    def selected_batch(self) -> Any | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        source = self.proxy_model.mapToSource(selected[0])
        return self.model.batch_at(source.row()) if source.isValid() else None

    def _emit_open_batch(self) -> None:
        batch = self.selected_batch()
        if batch is not None:
            self.open_batch_requested.emit(batch)

    def _emit_open_path(self, field_name: str) -> None:
        batch = self.selected_batch()
        if batch is None:
            return
        path = _field(batch, field_name)
        if path:
            self.open_path_requested.emit(Path(path))

    def _update_count(self, *_args: Any) -> None:
        self.count_label.setText(
            f"{self.proxy_model.rowCount():,}/{self.model.rowCount():,} batch".replace(",", ".")
        )

    def _update_actions(self, *_args: Any) -> None:
        batch = self.selected_batch()
        has_selection = batch is not None
        self.open_batch_button.setEnabled(has_selection)
        current_path = _field(batch, "source_output_path")
        self.current_file_action.setEnabled(
            has_selection and bool(current_path) and Path(current_path).is_file()
        )
        self.path_button.setEnabled(self.current_file_action.isEnabled())

"""Model bảng review và proxy tìm kiếm/lọc/sắp xếp.

Model nguồn luôn giữ thứ tự nghiệp vụ. Mọi thao tác sort/filter chỉ xảy ra ở
``ReviewFilterProxyModel`` nên dữ liệu serialize không bị đổi thứ tự ngoài ý muốn.
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, Final

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor

from .theme import ERROR_BG, MUTED_TEXT, SUCCESS_BG, WARNING_BG

try:
    from app.constants import (
        FEE_CATALOG as _CORE_FEE_CATALOG,
        RULE_CATALOG as _CORE_RULE_CATALOG,
        UNDETERMINED_RULE_LABEL as _UNDETERMINED_RULE_LABEL,
    )

    FEE_CATALOG: Final[OrderedDict[str, str]] = OrderedDict(
        _CORE_FEE_CATALOG.items()
    )
    RULE_CATALOG: Final[OrderedDict[str | None, str]] = OrderedDict(
        [(None, _UNDETERMINED_RULE_LABEL), *_CORE_RULE_CATALOG.items()]
    )
except ImportError:
    # Fallback giúp module UI vẫn độc lập khi được preview riêng trong Designer.
    FEE_CATALOG = OrderedDict(
        [
            ("CB", "Cước biển"),
            ("CBDH", "Cước bộ đóng hàng; gồm DtD, Dr-to-Dr và Door-to-Door"),
            ("VTN", "Cước bộ trả hàng"),
            ("NV", "Nâng vỏ, nâng container rỗng"),
            ("HH", "Hạ hàng, hạ container có hàng từ xe xuống bãi"),
            ("NH", "Nâng hàng, nâng container có hàng từ bãi lên xe"),
            ("HV", "Hạ vỏ, hạ container rỗng từ xe xuống bãi"),
            ("VSDL", "Vệ sinh, D/O, chứng từ, lệnh, điện, seal, THC/terminal"),
            ("LC", "Lưu container/vỏ/hàng, gia hạn, demurrage/detention/storage"),
            ("QT", "Quá tải, quá trọng lượng hoặc phụ thu trọng lượng"),
            ("LL", "Phí/công làm lệnh riêng"),
            ("SC", "Sửa chữa hoặc hư hỏng container"),
            ("CXD", "Chưa đủ căn cứ hoặc chưa có mã chính thức"),
        ]
    )
    RULE_CATALOG = OrderedDict(
        [
            (None, "Không xác định"),
            ("HD", "Tổng cộng tiền thanh toán của toàn hóa đơn"),
            ("ST", "Số tiền trực tiếp đã sau VAT"),
            ("CV", "Tiền trước thuế cộng VAT thực tế"),
            ("GV", "Gộp các dòng phù hợp rồi lấy tiền cuối cùng"),
        ]
    )


class RowStatus(str, Enum):
    """Trạng thái kiểm tra của một dòng."""

    VALID = "valid"
    WARNING = "warning"
    ERROR = "error"


STATUS_LABELS: Final[dict[RowStatus, str]] = {
    RowStatus.VALID: "Hợp lệ",
    RowStatus.WARNING: "Cảnh báo",
    RowStatus.ERROR: "Lỗi",
}


@dataclass(slots=True)
class ReviewRow:
    """Biểu diễn nội bộ của một dòng schema mảng 5 vị trí."""

    cont: Any = None
    bl: Any = None
    fee: Any = "CXD"
    rule: Any = None
    amount: Any = None

    def as_array(self) -> list[Any]:
        return [self.cont, self.bl, self.fee, self.rule, self.amount]


@dataclass(frozen=True, slots=True)
class RowValidation:
    """Kết quả validation hiển thị cho một dòng."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def status(self) -> RowStatus:
        if self.errors:
            return RowStatus.ERROR
        if self.warnings:
            return RowStatus.WARNING
        return RowStatus.VALID

    @property
    def messages(self) -> tuple[str, ...]:
        return self.errors + self.warnings


@dataclass(frozen=True, slots=True)
class ReviewStats:
    """Thống kê toàn bộ model sau validation."""

    total: int
    valid: int
    warning: int
    error: int
    with_container: int
    with_bl: int
    with_amount: int
    total_amount: int
    fee_counts: dict[str, int]


def _mapping_value(value: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in value:
            return value[name]
    return default


def coerce_review_row(value: Any) -> ReviewRow:
    """Chuyển dataclass/dict/list/object từ core thành ``ReviewRow``."""

    if isinstance(value, ReviewRow):
        return ReviewRow(*value.as_array())
    if isinstance(value, Mapping):
        return ReviewRow(
            _mapping_value(value, "cont", "container"),
            _mapping_value(value, "bl", "bill_of_lading", "bill"),
            _mapping_value(value, "fee", "fee_code", default="CXD"),
            _mapping_value(value, "rule", "rule_code"),
            _mapping_value(value, "amount"),
        )
    if is_dataclass(value):
        return coerce_review_row(asdict(value))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = list(value)
        if len(values) != 5:
            raise ValueError("Mỗi dòng dữ liệu phải có đúng 5 giá trị.")
        return ReviewRow(*values)
    attrs = [
        getattr(value, "cont", getattr(value, "container", None)),
        getattr(value, "bl", getattr(value, "bill_of_lading", None)),
        getattr(value, "fee", getattr(value, "fee_code", "CXD")),
        getattr(value, "rule", getattr(value, "rule_code", None)),
        getattr(value, "amount", None),
    ]
    if any(hasattr(value, name) for name in ("cont", "container", "fee", "fee_code")):
        return ReviewRow(*attrs)
    raise TypeError(f"Không thể chuyển kiểu {type(value).__name__} thành dòng dữ liệu.")


def validate_row(row: ReviewRow) -> RowValidation:
    """Kiểm tra các lỗi chặn/cảnh báo độc lập của một dòng."""

    errors: list[str] = []
    warnings: list[str] = []

    if row.cont is not None and not isinstance(row.cont, str):
        errors.append("Container phải là chuỗi hoặc null.")
    if row.bl is not None and not isinstance(row.bl, str):
        errors.append("B/L phải là chuỗi hoặc null.")
    if not isinstance(row.fee, str) or row.fee not in FEE_CATALOG:
        errors.append("Mã loại cước không thuộc danh mục chính thức.")
    if row.rule is not None and (not isinstance(row.rule, str) or row.rule not in RULE_CATALOG):
        errors.append("Mã xử lý tiền không hợp lệ.")
    if row.amount is not None:
        if isinstance(row.amount, bool) or not isinstance(row.amount, int):
            errors.append("Số tiền phải là số nguyên hoặc null.")
        elif row.amount < 0:
            errors.append("Số tiền không được âm.")

    if row.rule == "HD" and row.fee != "CB":
        errors.append("Quy tắc HD chỉ được dùng cho cước biển (CB).")
    if row.fee == "CB" and row.rule != "HD":
        errors.append("Cước biển (CB) bắt buộc dùng quy tắc HD.")

    if isinstance(row.cont, str) and row.cont:
        import re

        if re.fullmatch(r"[A-Z]{4}[0-9]{7}", row.cont) is None:
            warnings.append("Container không đúng mẫu 4 chữ cái và 7 chữ số.")
    if row.cont is None and row.bl is None:
        warnings.append("Cả container và B/L đều chưa xác định.")
    if row.fee == "CXD":
        warnings.append("Loại cước chưa đủ căn cứ (CXD).")
    if row.amount is None:
        warnings.append("Số tiền chưa xác định.")
    elif isinstance(row.amount, int) and not isinstance(row.amount, bool) and row.amount == 0:
        warnings.append("Số tiền bằng 0.")
    if row.rule is None:
        warnings.append("Quy tắc xử lý tiền chưa xác định.")
    if row.fee == "CB" and row.bl is None:
        warnings.append("Cước biển chưa có số B/L.")
    return RowValidation(tuple(errors), tuple(warnings))


class ReviewTableModel(QAbstractTableModel):
    """Model nguồn cho dữ liệu bóc tách, validation và dirty state."""

    dirtyChanged = Signal(bool)
    validationChanged = Signal(object)
    rowsChanged = Signal()

    COLUMN_NO = 0
    COLUMN_CONT = 1
    COLUMN_BL = 2
    COLUMN_FEE = 3
    COLUMN_FEE_NAME = 4
    COLUMN_RULE = 5
    COLUMN_RULE_NAME = 6
    COLUMN_AMOUNT = 7
    COLUMN_STATUS = 8
    COLUMN_MESSAGES = 9

    HEADERS: Final[tuple[str, ...]] = (
        "STT",
        "Container",
        "B/L",
        "Mã cước",
        "Tên loại cước",
        "Mã xử lý",
        "Diễn giải xử lý tiền",
        "Số tiền cuối cùng (VND)",
        "Trạng thái",
        "Cảnh báo / lỗi",
    )

    def __init__(
        self,
        rows: Iterable[Any] | None = None,
        parent: Any = None,
        *,
        validator: Callable[[list[list[Any]]], Any] | Any | None = None,
    ) -> None:
        super().__init__(parent)
        self._rows: list[ReviewRow] = []
        self._validation: list[RowValidation] = []
        self._stats = ReviewStats(0, 0, 0, 0, 0, 0, 0, 0, {})
        self._dirty = False
        self._validator = validator
        if rows is not None:
            self.set_rows(rows, mark_dirty=False)
        else:
            self._revalidate(emit_signal=False)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

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
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        if orientation == Qt.Orientation.Vertical:
            return section + 1
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        result = self._validation[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.UserRole:
            return self._raw_value(row, result, column, index.row())
        if role == Qt.ItemDataRole.UserRole + 1:
            return result.status.value
        if role == Qt.ItemDataRole.UserRole + 2:
            return row.as_array()
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_value(row, result, column, index.row())
        if role == Qt.ItemDataRole.ToolTipRole:
            messages = "\n".join(result.messages)
            return messages or "Dòng hợp lệ."
        if role == Qt.ItemDataRole.BackgroundRole:
            if result.status is RowStatus.ERROR:
                return QColor(ERROR_BG)
            if result.status is RowStatus.WARNING:
                return QColor(WARNING_BG)
            return QColor(SUCCESS_BG)
        if role == Qt.ItemDataRole.ForegroundRole:
            if column in (self.COLUMN_CONT, self.COLUMN_BL) and self._raw_value(
                row, result, column, index.row()
            ) is None:
                return QColor(MUTED_TEXT)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column in (self.COLUMN_NO, self.COLUMN_FEE, self.COLUMN_RULE, self.COLUMN_STATUS):
                return int(Qt.AlignmentFlag.AlignCenter)
            if column == self.COLUMN_AMOUNT:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    @classmethod
    def _raw_value(
        cls, row: ReviewRow, result: RowValidation, column: int, source_row: int
    ) -> Any:
        values: tuple[Any, ...] = (
            source_row + 1,
            row.cont,
            row.bl,
            row.fee,
            FEE_CATALOG.get(row.fee, "") if isinstance(row.fee, str) else "",
            row.rule,
            RULE_CATALOG.get(row.rule, "")
            if row.rule is None or isinstance(row.rule, str)
            else "",
            row.amount,
            result.status.value,
            "\n".join(result.messages),
        )
        return values[column] if 0 <= column < len(values) else None

    @classmethod
    def _display_value(
        cls, row: ReviewRow, result: RowValidation, column: int, source_row: int
    ) -> str | int:
        value = cls._raw_value(row, result, column, source_row)
        if column in (cls.COLUMN_CONT, cls.COLUMN_BL, cls.COLUMN_RULE) and value is None:
            return "—"
        if column == cls.COLUMN_AMOUNT:
            if value is None:
                return "—"
            if type(value) is int:
                return f"{value:,}".replace(",", ".")
            return str(value)
        if column == cls.COLUMN_STATUS:
            return STATUS_LABELS[result.status]
        if column == cls.COLUMN_MESSAGES:
            return "; ".join(result.messages) if result.messages else "Không có"
        return "" if value is None else value

    @property
    def dirty(self) -> bool:
        return self._dirty

    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def stats(self) -> ReviewStats:
        return self._stats

    def validation_at(self, row: int) -> RowValidation:
        return self._validation[row]

    def row_at(self, row: int) -> ReviewRow:
        source = self._rows[row]
        return ReviewRow(*source.as_array())

    def rows(self) -> list[ReviewRow]:
        return [ReviewRow(*row.as_array()) for row in self._rows]

    def rows_as_arrays(self) -> list[list[Any]]:
        return [row.as_array() for row in self._rows]

    def to_document(self) -> dict[str, Any]:
        return {"v": 1, "d": self.rows_as_arrays()}

    def set_rows(self, rows: Iterable[Any], *, mark_dirty: bool = False) -> None:
        converted = [coerce_review_row(row) for row in rows]
        self.beginResetModel()
        self._rows = converted
        self._revalidate(emit_signal=False)
        self.endResetModel()
        self._set_dirty(mark_dirty)
        self.validationChanged.emit(self._stats)
        self.rowsChanged.emit()

    def set_document(self, document: Any, *, mark_dirty: bool = False) -> None:
        if isinstance(document, Mapping):
            rows = document.get("d", document.get("rows", []))
        else:
            rows = getattr(document, "d", getattr(document, "rows", document))
        self.set_rows(rows, mark_dirty=mark_dirty)

    def add_row(self, row: Any, position: int | None = None) -> int:
        converted = coerce_review_row(row)
        target = len(self._rows) if position is None else max(0, min(position, len(self._rows)))
        self.beginInsertRows(QModelIndex(), target, target)
        self._rows.insert(target, converted)
        self._validation.insert(target, RowValidation())
        self.endInsertRows()
        self._after_mutation()
        return target

    def update_row(self, position: int, row: Any) -> None:
        if not (0 <= position < len(self._rows)):
            raise IndexError("Dòng cần sửa không tồn tại.")
        self._rows[position] = coerce_review_row(row)
        self._after_mutation()

    def remove_row(self, position: int) -> ReviewRow:
        if not (0 <= position < len(self._rows)):
            raise IndexError("Dòng cần xóa không tồn tại.")
        self.beginRemoveRows(QModelIndex(), position, position)
        removed = self._rows.pop(position)
        self._validation.pop(position)
        self.endRemoveRows()
        self._after_mutation()
        return removed

    def mark_clean(self) -> None:
        self._set_dirty(False)

    def mark_dirty(self) -> None:
        self._set_dirty(True)

    def revalidate(self) -> ReviewStats:
        self._revalidate(emit_signal=True)
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, self.columnCount() - 1),
            )
        return self._stats

    def first_error_row(self) -> int | None:
        return next(
            (index for index, result in enumerate(self._validation) if result.errors),
            None,
        )

    def _set_dirty(self, dirty: bool) -> None:
        if self._dirty == dirty:
            return
        self._dirty = dirty
        self.dirtyChanged.emit(dirty)

    def _after_mutation(self) -> None:
        self._revalidate(emit_signal=False)
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, self.columnCount() - 1),
            )
        self._set_dirty(True)
        self.validationChanged.emit(self._stats)
        self.rowsChanged.emit()

    def _revalidate(self, *, emit_signal: bool) -> None:
        results = [validate_row(row) for row in self._rows]
        duplicate_keys = [tuple(repr(value) for value in row.as_array()) for row in self._rows]
        duplicate_counts = Counter(duplicate_keys)
        for index, row in enumerate(self._rows):
            if duplicate_counts[duplicate_keys[index]] > 1:
                result = results[index]
                results[index] = RowValidation(
                    result.errors,
                    result.warnings + ("Dòng có đủ 5 giá trị trùng hoàn toàn với dòng khác.",),
                )

        external = self._run_external_validator()
        if external:
            results = self._merge_external_results(results, external)
        self._validation = results
        status_counts = Counter(result.status for result in results)
        valid_amounts = [
            row.amount
            for row in self._rows
            if isinstance(row.amount, int) and not isinstance(row.amount, bool) and row.amount >= 0
        ]
        self._stats = ReviewStats(
            total=len(self._rows),
            valid=status_counts[RowStatus.VALID],
            warning=status_counts[RowStatus.WARNING],
            error=status_counts[RowStatus.ERROR],
            with_container=sum(row.cont is not None for row in self._rows),
            with_bl=sum(row.bl is not None for row in self._rows),
            with_amount=len(valid_amounts),
            total_amount=sum(valid_amounts),
            fee_counts=dict(Counter(str(row.fee) for row in self._rows)),
        )
        if emit_signal:
            self.validationChanged.emit(self._stats)

    def _run_external_validator(self) -> Any:
        if self._validator is None:
            return None
        try:
            if callable(self._validator):
                return self._validator(self.rows_as_arrays())
            for name in ("validate_rows", "validate_document", "validate"):
                method = getattr(self._validator, name, None)
                if callable(method):
                    payload: Any = self.to_document() if name == "validate_document" else self.rows_as_arrays()
                    return method(payload)
        except Exception:
            # Validation nội bộ vẫn đảm bảo UI hoạt động; lỗi service sẽ được lớp điều
            # phối ghi log/hiển thị thay vì làm model Qt sập.
            return None
        return None

    @staticmethod
    def _merge_external_results(
        current: list[RowValidation], external: Any
    ) -> list[RowValidation]:
        row_results = getattr(external, "row_results", getattr(external, "rows", external))
        if not isinstance(row_results, Sequence) or isinstance(row_results, (str, bytes)):
            return current
        merged = list(current)
        for index, value in enumerate(row_results[: len(merged)]):
            errors = getattr(value, "errors", ())
            warnings = getattr(value, "warnings", ())
            if isinstance(value, Mapping):
                errors = value.get("errors", errors)
                warnings = value.get("warnings", warnings)
            extra_errors = [str(item) for item in (errors or ())]
            extra_warnings = [str(item) for item in (warnings or ())]
            for issue in getattr(value, "issues", ()) or ():
                message = str(getattr(issue, "message", issue))
                severity = str(getattr(issue, "severity", "")).casefold()
                if "error" in severity or "lỗi" in severity:
                    extra_errors.append(message)
                elif "warning" in severity or "cảnh báo" in severity:
                    extra_warnings.append(message)
            if extra_errors or extra_warnings:
                old = merged[index]
                merged[index] = RowValidation(
                    tuple(dict.fromkeys(old.errors + tuple(extra_errors))),
                    tuple(dict.fromkeys(old.warnings + tuple(extra_warnings))),
                )
        return merged


class ReviewFilterProxyModel(QSortFilterProxyModel):
    """Proxy tìm container/B/L, lọc fee/trạng thái và sort an toàn."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._search_text = ""
        self._fee = ""
        self._status = ""
        self.setDynamicSortFilter(True)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_search_text(self, text: str) -> None:
        modern = self._begin_filter_update()
        self._search_text = text.strip().casefold()
        self._end_filter_update(modern)

    def set_fee_filter(self, fee: str | None) -> None:
        modern = self._begin_filter_update()
        self._fee = (fee or "").strip().upper()
        self._end_filter_update(modern)

    def set_status_filter(self, status: str | RowStatus | None) -> None:
        modern = self._begin_filter_update()
        if isinstance(status, RowStatus):
            self._status = status.value
        else:
            normalized = (status or "").strip().casefold()
            labels = {
                "hợp lệ": RowStatus.VALID.value,
                "cảnh báo": RowStatus.WARNING.value,
                "lỗi": RowStatus.ERROR.value,
            }
            self._status = labels.get(normalized, normalized)
        self._end_filter_update(modern)

    def clear_filters(self) -> None:
        modern = self._begin_filter_update()
        self._search_text = ""
        self._fee = ""
        self._status = ""
        self._end_filter_update(modern)

    def _begin_filter_update(self) -> bool:
        begin = getattr(self, "beginFilterChange", None)
        if callable(begin):
            begin()
            return True
        return False

    def _end_filter_update(self, modern: bool) -> None:
        if modern:
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self.invalidateFilter()

    def filterAcceptsRow(  # noqa: N802
        self, source_row: int, source_parent: QModelIndex
    ) -> bool:
        model = self.sourceModel()
        if model is None:
            return False
        if self._search_text:
            cont = model.index(source_row, ReviewTableModel.COLUMN_CONT, source_parent).data(
                Qt.ItemDataRole.UserRole
            )
            bl = model.index(source_row, ReviewTableModel.COLUMN_BL, source_parent).data(
                Qt.ItemDataRole.UserRole
            )
            haystack = f"{cont or ''} {bl or ''}".casefold()
            if self._search_text not in haystack:
                return False
        if self._fee:
            fee = model.index(source_row, ReviewTableModel.COLUMN_FEE, source_parent).data(
                Qt.ItemDataRole.UserRole
            )
            if str(fee).upper() != self._fee:
                return False
        if self._status:
            status = model.index(source_row, ReviewTableModel.COLUMN_STATUS, source_parent).data(
                Qt.ItemDataRole.UserRole + 1
            )
            if str(status).casefold() != self._status:
                return False
        return True

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        left_value = left.data(Qt.ItemDataRole.UserRole)
        right_value = right.data(Qt.ItemDataRole.UserRole)
        if left_value is None and right_value is not None:
            return False
        if right_value is None and left_value is not None:
            return True
        if isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)):
            return left_value < right_value
        return str(left_value or "").casefold() < str(right_value or "").casefold()


# Alias dễ hiểu cho test/tích hợp bên ngoài.
ReviewSortFilterProxyModel = ReviewFilterProxyModel

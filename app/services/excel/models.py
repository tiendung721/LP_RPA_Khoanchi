"""Pure-Python contracts used by the Excel workflows.

The UI deliberately consumes these value objects instead of importing openpyxl.
Keeping the plans serialisable-ish also makes conflict dialogs and audit logging
straightforward.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence


class ExcelOperation(str, Enum):
    DAILY_SYNC = "DAILY_SYNC"
    EXPENSE_POSTING = "EXPENSE_POSTING"


class ExcelRunStatus(str, Enum):
    ANALYZING = "ANALYZING"
    WAITING_USER = "WAITING_USER"
    APPLYING = "APPLYING"
    SUCCEEDED = "SUCCEEDED"
    NO_CHANGES = "NO_CHANGES"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class PostingItemStatus(str, Enum):
    PLANNED = "PLANNED"
    POSTED = "POSTED"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    USER_SKIPPED = "USER_SKIPPED"
    NOT_MATCHED = "NOT_MATCHED"
    UNRESOLVED = "UNRESOLVED"
    FAILED = "FAILED"


class ConflictType(str, Enum):
    INVALID_SQT = "INVALID_SQT"
    DUPLICATE_SOURCE_ROW = "DUPLICATE_SOURCE_ROW"
    TARGET_MONTH_AMBIGUOUS = "TARGET_MONTH_AMBIGUOUS"
    TARGET_SHEET_AMBIGUOUS = "TARGET_SHEET_AMBIGUOUS"
    CONTAINER_NOT_FOUND = "CONTAINER_NOT_FOUND"
    MULTIPLE_CONTAINER_MATCH = "MULTIPLE_CONTAINER_MATCH"
    TARGET_CELL_OCCUPIED = "TARGET_CELL_OCCUPIED"
    TARGET_CELL_FORMULA = "TARGET_CELL_FORMULA"
    TARGET_CELL_TEXT = "TARGET_CELL_TEXT"
    UNKNOWN_FEE_CODE = "UNKNOWN_FEE_CODE"
    FEE_COLUMN_MISSING = "FEE_COLUMN_MISSING"
    BL_ONLY_NO_CONTAINER = "BL_ONLY_NO_CONTAINER"
    BATCH_ALREADY_POSTED = "BATCH_ALREADY_POSTED"
    FILE_CHANGED = "FILE_CHANGED"
    FILE_LOCKED = "FILE_LOCKED"


class ResolutionAction(str, Enum):
    SKIP_INVALID = "SKIP_INVALID"
    KEEP_ONE = "KEEP_ONE"
    KEEP_ALL = "KEEP_ALL"
    CANCEL_ALL = "CANCEL_ALL"
    SELECT_MONTH = "SELECT_MONTH"
    SELECT_SHEET = "SELECT_SHEET"
    SELECT_ROW = "SELECT_ROW"
    SELECT_FEE = "SELECT_FEE"
    KEEP_EXISTING = "KEEP_EXISTING"
    KEEP_FORMULA = "KEEP_FORMULA"
    OVERWRITE = "OVERWRITE"
    ADD = "ADD"
    SKIP = "SKIP"
    POST_UNPOSTED_ONLY = "POST_UNPOSTED_ONLY"
    REANALYZE = "REANALYZE"
    RETRY = "RETRY"
    CANCEL = "CANCEL"


class TargetCellKind(str, Enum):
    EMPTY = "EMPTY"
    ZERO = "ZERO"
    SAME_VALUE = "SAME_VALUE"
    NUMBER = "NUMBER"
    FORMULA = "FORMULA"
    TEXT = "TEXT"


@dataclass(frozen=True, slots=True)
class WorkbookFingerprint:
    size: int
    mtime_ns: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "sha256": self.sha256,
        }

    @classmethod
    def from_value(
        cls, value: "WorkbookFingerprint | Mapping[str, Any]"
    ) -> "WorkbookFingerprint":
        if isinstance(value, cls):
            return value
        return cls(
            size=int(value["size"]),
            mtime_ns=int(value["mtime_ns"]),
            sha256=str(value["sha256"]),
        )


@dataclass(frozen=True, slots=True)
class TargetCellState:
    kind: TargetCellKind
    value: Any
    coordinate: str
    data_type: str | None = None


@dataclass(slots=True)
class SourceSheetCandidate:
    month: int
    source_sheet: str

    @property
    def sheet_name(self) -> str:
        return self.source_sheet


@dataclass(slots=True)
class MonthCandidate:
    month: int
    source_sheet: str
    target_sheet: str
    new_row_count: int = 0
    last_sqt: int = 0
    match_count: int = 0
    recently_synced: bool = False
    year: int | None = None

    @property
    def sheet_name(self) -> str:
        return self.target_sheet


@dataclass(slots=True)
class SyncRow:
    source_sheet: str
    source_row: int
    month: int
    sqt: int
    values: tuple[Any, ...]
    duplicate_key: tuple[Any, ...]

    @property
    def container(self) -> Any:
        return self.values[2] if len(self.values) > 2 else None


@dataclass(slots=True)
class SyncConflict:
    conflict_id: str
    conflict_type: ConflictType
    message: str
    source_sheet: str | None = None
    source_row: int | None = None
    sqt: int | None = None
    container: str | None = None
    allowed_actions: tuple[ResolutionAction, ...] = ()
    default_action: ResolutionAction | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.conflict_id

    @property
    def type(self) -> ConflictType:
        return self.conflict_type

    @property
    def options(self) -> tuple[ResolutionAction, ...]:
        return self.allowed_actions

    @property
    def default_resolution(self) -> ResolutionAction | None:
        return self.default_action


@dataclass(slots=True)
class SyncResolution:
    conflict_id: str
    action: ResolutionAction | str
    selected_month: int | None = None
    selected_sheet: str | None = None


@dataclass(slots=True)
class SyncPlan:
    source_path: Path
    source_snapshot_path: Path
    target_path: Path
    source_fingerprint: WorkbookFingerprint
    target_fingerprint: WorkbookFingerprint
    month_candidates: list[MonthCandidate]
    rows_by_month: dict[int, list[SyncRow]]
    source_year: int | None = None
    target_year: int | None = None
    rows_by_target: dict[str, list[SyncRow]] = field(default_factory=dict)
    source_snapshot_fingerprint: WorkbookFingerprint | None = None
    conflicts: list[SyncConflict] = field(default_factory=list)
    selected_month: int | None = None
    selected_target_sheet: str | None = None
    run_id: int | None = None

    @property
    def operation(self) -> ExcelOperation:
        return ExcelOperation.DAILY_SYNC

    @property
    def rows(self) -> list[SyncRow]:
        if self.selected_target_sheet is not None and self.rows_by_target:
            return list(self.rows_by_target.get(self.selected_target_sheet, ()))
        if self.selected_month is None:
            return []
        return list(self.rows_by_month.get(self.selected_month, ()))

    @property
    def selected_sheet(self) -> str | None:
        if self.selected_target_sheet is not None:
            return self.selected_target_sheet
        for candidate in self.month_candidates:
            if candidate.month == self.selected_month:
                return candidate.target_sheet
        return None

    @property
    def has_changes(self) -> bool:
        return any(
            (self.rows_by_target or self.rows_by_month).values()
        )

    @property
    def requires_user_input(self) -> bool:
        return self.selected_sheet is None or any(
            conflict.default_action is None for conflict in self.conflicts
        )


@dataclass(slots=True)
class SyncResult:
    status: ExcelRunStatus
    target_path: Path
    sheet_name: str | None = None
    added_rows: int = 0
    skipped_rows: int = 0
    conflict_count: int = 0
    backup_path: Path | None = None
    fingerprint_before: WorkbookFingerprint | None = None
    fingerprint_after: WorkbookFingerprint | None = None
    run_id: int | None = None
    message: str = ""

    @property
    def operation(self) -> ExcelOperation:
        return ExcelOperation.DAILY_SYNC


@dataclass(slots=True)
class RowCandidate:
    row: int
    sqt: int | None
    container: str | None
    cargo_type: Any = None
    closing_date: Any = None
    vessel: Any = None
    recipient: Any = None
    is_ron: bool = False


@dataclass(slots=True)
class PostingItem:
    source_indices: list[int]
    container: str | None
    bl: str | None
    original_fee: str
    selected_fee: str
    rule: str | None
    amount: int
    sheet_name: str | None = None
    target_row: int | None = None
    target_column: int | None = None
    target_cell: str | None = None
    current_value: Any = None
    cell_state: TargetCellState | None = None
    action: ResolutionAction | None = None
    status: PostingItemStatus = PostingItemStatus.PLANNED
    row_candidates: list[RowCandidate] = field(default_factory=list)
    source_items: list[dict[str, Any]] = field(default_factory=list)
    force_repost: bool = False

    @property
    def fee(self) -> str:
        return self.selected_fee

    @property
    def row(self) -> int | None:
        return self.target_row

    @property
    def column(self) -> int | None:
        return self.target_column

    @property
    def cell(self) -> str | None:
        return self.target_cell


@dataclass(slots=True)
class PostingConflict:
    conflict_id: str
    conflict_type: ConflictType
    message: str
    item_index: int | None = None
    container: str | None = None
    bl: str | None = None
    sqt: int | None = None
    fee: str | None = None
    amount: int | None = None
    sheet_name: str | None = None
    target_row: int | None = None
    target_column: int | None = None
    target_cell: str | None = None
    current_value: Any = None
    allowed_actions: tuple[ResolutionAction, ...] = ()
    default_action: ResolutionAction | None = None
    row_candidates: list[RowCandidate] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.conflict_id

    @property
    def type(self) -> ConflictType:
        return self.conflict_type

    @property
    def options(self) -> tuple[ResolutionAction, ...]:
        return self.allowed_actions

    @property
    def default_resolution(self) -> ResolutionAction | None:
        return self.default_action


@dataclass(slots=True)
class PostingResolution:
    conflict_id: str
    action: ResolutionAction | str
    selected_sheet: str | None = None
    selected_row: int | None = None
    selected_fee: str | None = None


@dataclass(slots=True)
class PostingPlan:
    batch_id: int | None
    batch_path: Path
    batch_hash: str
    target_path: Path
    target_fingerprint: WorkbookFingerprint
    items: list[PostingItem]
    conflicts: list[PostingConflict]
    sheet_candidates: list[MonthCandidate]
    selected_sheet: str | None = None
    source_item_count: int = 0
    already_posted_indices: set[int] = field(default_factory=set)
    previously_posted_items: list[Any] = field(default_factory=list)
    repost_source_indices: set[int] = field(default_factory=set)
    repost_selection_done: bool = False
    run_id: int | None = None

    @property
    def operation(self) -> ExcelOperation:
        return ExcelOperation.EXPENSE_POSTING

    @property
    def requires_user_input(self) -> bool:
        return (
            self.selected_sheet is None
            or (
                bool(self.previously_posted_items)
                and not self.repost_selection_done
            )
            or bool(self.conflicts)
        )

    @property
    def has_changes(self) -> bool:
        return any(
            item.status is PostingItemStatus.PLANNED
            and item.action not in {
                ResolutionAction.SKIP,
                ResolutionAction.KEEP_EXISTING,
                ResolutionAction.KEEP_FORMULA,
            }
            for item in self.items
        )


@dataclass(slots=True)
class PostingResult:
    status: ExcelRunStatus
    target_path: Path
    sheet_name: str | None = None
    posted_source_items: int = 0
    written_cells: int = 0
    skipped_source_items: int = 0
    already_existing_items: int = 0
    conflict_count: int = 0
    backup_path: Path | None = None
    fingerprint_before: WorkbookFingerprint | None = None
    fingerprint_after: WorkbookFingerprint | None = None
    run_id: int | None = None
    message: str = ""

    @property
    def operation(self) -> ExcelOperation:
        return ExcelOperation.EXPENSE_POSTING


Plan = SyncPlan | PostingPlan
Result = SyncResult | PostingResult
Resolution = SyncResolution | PostingResolution


def resolution_map(
    resolutions: Mapping[str, Any] | Sequence[Any] | None,
) -> dict[str, Any]:
    if resolutions is None:
        return {}
    if isinstance(resolutions, Mapping):
        return dict(resolutions)
    result: dict[str, Any] = {}
    for value in resolutions:
        conflict_id = getattr(value, "conflict_id", getattr(value, "id", None))
        if conflict_id is None:
            raise ValueError("Mỗi resolution phải có conflict_id.")
        result[str(conflict_id)] = value
    return result

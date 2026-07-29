"""Two-phase synchronization from the read-only daily workbook into BK."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from openpyxl.cell.cell import MergedCell
from openpyxl.worksheet.worksheet import Worksheet

from app.services.file_stability import FileStabilityChecker

from .headers import HeaderResolution, HeaderResolutionError, HeaderResolver
from .models import (
    ConflictType,
    ExcelOperation,
    ExcelRunStatus,
    MonthCandidate,
    ResolutionAction,
    SyncConflict,
    SyncPlan,
    SyncResolution,
    SyncResult,
    SyncRow,
    resolution_map,
)
from .resolvers import MonthSheetService, YearResolver
from .workbook import (
    ExcelBackupService,
    ExcelLockService,
    WorkbookChangedError,
    WorkbookGateway,
    ensure_supported_workbook,
)


ProgressCallback = Callable[[str], None] | None

SYNC_FIELDS: tuple[str, ...] = (
    "sqt",
    "closing_date",
    "container",
    "weight",
    "cargo_type",
    "closing_place",
    "vessel",
    "departure_date",
    "estimated_delivery",
    "recipient",
    "sea_transport",
    "transport",
)

SOURCE_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "sqt": ("SQT PM", "SQT", "Số thứ tự PM"),
    "closing_date": ("Ngày Đóng", "Ngày đóng hàng"),
    "container": ("Số Container", "Container", "Số cont"),
    "weight": ("Số tấn", "Trọng lượng", "Số lượng tấn"),
    "cargo_type": ("Loại hàng", "Tên hàng"),
    "closing_place": ("Nơi đóng", "Địa điểm đóng"),
    "vessel": ("Tên tàu", "Tàu"),
    "departure_date": ("Ngày chạy", "Ngày tàu chạy"),
    "estimated_delivery": ("Dự kiến giao", "Ngày dự kiến giao"),
    "recipient": ("Người nhận", "Khách hàng"),
    "sea_transport": ("VT biển", "Vận tải biển"),
    "transport": ("Vận chuyển", "Đơn vị vận chuyển"),
}

TARGET_EXPECTED_COLUMNS: dict[str, int] = {
    **{field: index for index, field in enumerate(SYNC_FIELDS[:11], 1)},
    "transport": 16,
}


class DailySyncError(RuntimeError):
    pass


def parse_sqt(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if type(value) is int:
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value > 0 else None
    if isinstance(value, str):
        text = "".join(value.split())
        if text.isdigit():
            parsed = int(text)
            return parsed if parsed > 0 else None
    return None


def _stable_id(*parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _progress(callback: ProgressCallback, message: str) -> None:
    if callback is not None:
        callback(message)


def _settings_value(settings: Any, name: str, default: Any = None) -> Any:
    return getattr(settings, name, default) if settings is not None else default


class DailySyncService:
    def __init__(
        self,
        settings: Any | None = None,
        *,
        daily_path: str | Path | None = None,
        bk_path: str | Path | None = None,
        temp_dir: str | Path | None = None,
        backup_dir: str | Path | None = None,
        gateway: WorkbookGateway | None = None,
        lock_service: ExcelLockService | None = None,
        stability_checker: FileStabilityChecker | None = None,
        header_resolver: HeaderResolver | None = None,
        month_service: MonthSheetService | None = None,
        year_resolver: YearResolver | None = None,
        run_repository: Any | None = None,
    ) -> None:
        paths = getattr(settings, "paths", None)
        self.daily_path = Path(
            daily_path
            or _settings_value(settings, "daily_workbook_path", "")
        )
        self.bk_path = Path(
            bk_path or _settings_value(settings, "bk_workbook_path", "")
        )
        system_dir = getattr(paths, "system_dir", Path("Output") / "_system")
        self.temp_dir = Path(
            temp_dir
            or getattr(paths, "excel_temp_dir", system_dir / "Excel" / "Temp")
        )
        self.backup_dir = Path(
            backup_dir
            or getattr(paths, "excel_backup_dir", system_dir / "Excel" / "Backup")
        )
        self.gateway = gateway or WorkbookGateway()
        self.lock_service = lock_service or ExcelLockService()
        self.stability_checker = stability_checker or FileStabilityChecker()
        self.headers = header_resolver or HeaderResolver()
        self.months = month_service or MonthSheetService()
        self.years = year_resolver or YearResolver()
        self.run_repository = run_repository
        # Working copy phải nằm cạnh BK để os.replace luôn cùng filesystem.
        # Temp vẫn chỉ dùng cho snapshot nguồn LAN.
        self.backups = ExcelBackupService(self.backup_dir)

    def analyze(
        self, progress_callback: ProgressCallback = None
    ) -> SyncPlan:
        source = ensure_supported_workbook(self.daily_path)
        target = ensure_supported_workbook(self.bk_path)
        if not source.is_file():
            raise DailySyncError(f"Không tìm thấy file Hàng ngày: {source}")
        if not target.is_file():
            raise DailySyncError(f"Không tìm thấy file BK: {target}")

        run_id = self._create_run(source, target)
        source_snapshot: Path | None = None
        try:
            _progress(progress_callback, "Đang chờ file Hàng ngày ổn định…")
            self.stability_checker.wait(source)
            self.lock_service.ensure_readable(source)
            self.lock_service.ensure_readable(target)
            source_fingerprint = self.gateway.fingerprint(source)
            target_fingerprint = self.gateway.fingerprint(target)

            _progress(progress_callback, "Đang tạo bản đọc tạm của file Hàng ngày…")
            source_snapshot = self.gateway.source_snapshot(source, self.temp_dir)
            source_snapshot_fingerprint = self.gateway.fingerprint(source_snapshot)
            source_book = self.gateway.load(source_snapshot, read_only=True)
            target_book = self.gateway.load(target, read_only=False)
            try:
                source_year = self.years.from_filename(source)
                target_year = self.years.target_year(target, target_book.sheetnames)
                if source_year != target_year:
                    raise DailySyncError(
                        f"Năm file Hàng ngày ({source_year}) không khớp BK ({target_year})."
                    )
                source_sheets = self.months.daily_sheets(source_book.sheetnames)
                if not source_sheets:
                    raise DailySyncError(
                        "File Hàng ngày không có sheet Tháng 1…Tháng 12."
                    )
                target_sheets = self.months.target_sheets(
                    target_book.sheetnames, year=target_year
                )
                rows_by_month: dict[int, list[SyncRow]] = {}
                candidates: list[MonthCandidate] = []
                conflicts: list[SyncConflict] = []
                for month, source_sheet_name in sorted(source_sheets.items()):
                    _progress(
                        progress_callback,
                        f"Đang phân tích {source_sheet_name}…",
                    )
                    source_sheet = source_book[source_sheet_name]
                    source_headers = self.headers.resolve(
                        source_sheet, SOURCE_HEADER_ALIASES, required=SYNC_FIELDS
                    )
                    target_sheet_name = target_sheets.get(
                        month, self.months.target_name(month, target_year)
                    )
                    last_sqt = 0
                    if month in target_sheets:
                        target_sheet = target_book[target_sheet_name]
                        target_headers = self._resolve_target_headers(target_sheet)
                        last_sqt = self._last_sqt(target_sheet, target_headers)
                    month_rows, month_conflicts = self._source_rows(
                        source_sheet,
                        source_headers,
                        month=month,
                        last_sqt=last_sqt,
                        source_fingerprint=source_fingerprint.sha256,
                    )
                    conflicts.extend(month_conflicts)
                    if month_rows:
                        rows_by_month[month] = month_rows
                        candidates.append(
                            MonthCandidate(
                                month=month,
                                source_sheet=source_sheet_name,
                                target_sheet=target_sheet_name,
                                new_row_count=len(month_rows),
                                last_sqt=last_sqt,
                            )
                        )
            finally:
                source_book.close()
                target_book.close()

            selected_month = candidates[0].month if len(candidates) == 1 else None
            if len(candidates) > 1:
                conflicts.append(
                    SyncConflict(
                        conflict_id=_stable_id(
                            "sync-month",
                            source_fingerprint.sha256,
                            [candidate.month for candidate in candidates],
                        ),
                        conflict_type=ConflictType.TARGET_MONTH_AMBIGUOUS,
                        message="Có dữ liệu mới ở nhiều tháng; hãy chọn một tháng.",
                        allowed_actions=(
                            ResolutionAction.SELECT_MONTH,
                            ResolutionAction.CANCEL_ALL,
                        ),
                        details={
                            "months": [candidate.month for candidate in candidates]
                        },
                    )
                )
            plan = SyncPlan(
                source_path=source,
                source_snapshot_path=source_snapshot,
                target_path=target,
                source_fingerprint=source_fingerprint,
                target_fingerprint=target_fingerprint,
                source_year=source_year,
                target_year=target_year,
                month_candidates=candidates,
                rows_by_month=rows_by_month,
                source_snapshot_fingerprint=source_snapshot_fingerprint,
                conflicts=conflicts,
                selected_month=selected_month,
                run_id=run_id,
            )
            status = (
                ExcelRunStatus.NO_CHANGES
                if not plan.has_changes
                else ExcelRunStatus.WAITING_USER
                if plan.conflicts or selected_month is None
                else ExcelRunStatus.ANALYZING
            )
            self._update_run(
                run_id,
                status=status,
                source_fingerprint=source_fingerprint,
                target_fingerprint_before=target_fingerprint,
                sheet_name=plan.selected_sheet,
                total_items=sum(len(rows) for rows in rows_by_month.values()),
                conflict_count=len(conflicts),
            )
            return plan
        except Exception as exc:
            if source_snapshot is not None:
                source_snapshot.unlink(missing_ok=True)
            self._finish_failed(run_id, exc)
            raise

    def apply(
        self,
        plan: SyncPlan,
        resolutions: Mapping[str, Any] | Sequence[SyncResolution] | None = None,
        progress_callback: ProgressCallback = None,
    ) -> SyncResult:
        resolved = resolution_map(resolutions)
        try:
            month = self._selected_month(plan, resolved)
            if month is None:
                if not plan.has_changes:
                    result = SyncResult(
                        status=ExcelRunStatus.NO_CHANGES,
                        target_path=plan.target_path,
                        conflict_count=len(plan.conflicts),
                        fingerprint_before=plan.target_fingerprint,
                        fingerprint_after=plan.target_fingerprint,
                        run_id=plan.run_id,
                        message="Không có dòng SQT mới.",
                    )
                    self._finish_result(result)
                    plan.source_snapshot_path.unlink(missing_ok=True)
                    return result
                raise DailySyncError("Chưa chọn tháng cần đồng bộ.")
            rows, skipped = self._resolved_rows(plan, month, resolved)
            if not rows:
                result = SyncResult(
                    status=ExcelRunStatus.NO_CHANGES,
                    target_path=plan.target_path,
                    sheet_name=self.months.target_name(month, plan.target_year),
                    skipped_rows=skipped,
                    conflict_count=len(plan.conflicts),
                    fingerprint_before=plan.target_fingerprint,
                    fingerprint_after=plan.target_fingerprint,
                    run_id=plan.run_id,
                    message="Không còn dòng nào sau khi áp dụng lựa chọn.",
                )
                self._finish_result(result)
                plan.source_snapshot_path.unlink(missing_ok=True)
                return result
        except Exception as exc:
            plan.source_snapshot_path.unlink(missing_ok=True)
            self._finish_failed(plan.run_id, exc)
            raise

        self._update_run(plan.run_id, status=ExcelRunStatus.APPLYING)
        _progress(progress_callback, "Đang kiểm tra file chưa thay đổi…")
        try:
            self.gateway.assert_unchanged(
                plan.source_snapshot_path,
                plan.source_snapshot_fingerprint or plan.source_fingerprint,
                label="Bản đọc tạm Hàng ngày",
            )
            self.gateway.assert_unchanged(
                plan.target_path, plan.target_fingerprint, label="File BK"
            )
        except Exception as exc:
            plan.source_snapshot_path.unlink(missing_ok=True)
            self._finish_failed(plan.run_id, exc)
            raise
        backup_path: Path | None = None
        working_path: Path | None = None
        try:
            # Probe the Windows byte lock, then release our own handle before
            # hashing/copying/replacing. Holding it would make this process block
            # itself on Windows.
            with self.lock_service.acquire(plan.target_path):
                pass
            self.gateway.assert_unchanged(
                plan.target_path, plan.target_fingerprint, label="File BK"
            )
            _progress(progress_callback, "Đang tạo backup file BK…")
            backup_path = self.backups.create_backup(
                plan.target_path, run_id=plan.run_id
            )
            working_path = self.backups.create_working_copy(
                plan.target_path, run_id=plan.run_id
            )
            workbook = self.gateway.load(working_path, read_only=False)
            try:
                target_name = self.months.target_name(month, plan.target_year)
                created = target_name not in workbook.sheetnames
                if created:
                    worksheet = self._create_month_sheet(
                        workbook, month, plan.target_year, target_name
                    )
                else:
                    worksheet = workbook[target_name]
                header = self._resolve_target_headers(worksheet)
                old_snapshot = self._worksheet_snapshot(worksheet)
                append_at = self._last_data_row(worksheet, header) + 1
                template_row = max(header.row_end + 1, append_at - 1)
                for offset, sync_row in enumerate(rows):
                    target_row = append_at + offset
                    self._copy_row_style(
                        worksheet, template_row, target_row
                    )
                    for source_index, field in enumerate(SYNC_FIELDS[:11]):
                        worksheet.cell(target_row, source_index + 1).value = (
                            sync_row.values[source_index]
                        )
                    worksheet.cell(target_row, 16).value = sync_row.values[11]
                self.gateway.save(workbook, working_path)
            finally:
                workbook.close()

            _progress(progress_callback, "Đang kiểm tra bản BK mới…")
            self._verify_saved_sync(
                working_path,
                target_name,
                old_snapshot,
                append_at,
                rows,
                created=created,
            )
            after = self.gateway.atomic_replace(
                working_path,
                plan.target_path,
                expected=plan.target_fingerprint,
            )
            working_path = None
            result = SyncResult(
                status=ExcelRunStatus.SUCCEEDED,
                target_path=plan.target_path,
                sheet_name=target_name,
                added_rows=len(rows),
                skipped_rows=skipped,
                conflict_count=len(plan.conflicts),
                backup_path=backup_path,
                fingerprint_before=plan.target_fingerprint,
                fingerprint_after=after,
                run_id=plan.run_id,
                message=f"Đã thêm {len(rows)} dòng vào {target_name}.",
            )
            self._finish_result(result)
            return result
        except Exception as exc:
            self._finish_failed(plan.run_id, exc)
            raise
        finally:
            if working_path is not None and working_path.exists():
                working_path.unlink()
            plan.source_snapshot_path.unlink(missing_ok=True)

    def cancel(self, plan: SyncPlan) -> None:
        """Đánh dấu plan chờ người dùng là đã hủy và dọn snapshot tạm."""

        plan.source_snapshot_path.unlink(missing_ok=True)
        if self.run_repository is not None and plan.run_id is not None:
            self.run_repository.finish_run(
                plan.run_id,
                status=ExcelRunStatus.CANCELLED,
                total_items=sum(
                    len(rows) for rows in plan.rows_by_month.values()
                ),
                changed_items=0,
                skipped_items=0,
                conflict_count=len(plan.conflicts),
            )

    def _source_rows(
        self,
        worksheet: Worksheet,
        header: HeaderResolution,
        *,
        month: int,
        last_sqt: int,
        source_fingerprint: str,
    ) -> tuple[list[SyncRow], list[SyncConflict]]:
        rows: list[SyncRow] = []
        conflicts: list[SyncConflict] = []
        for row_index in range(header.row_end + 1, worksheet.max_row + 1):
            values = tuple(
                worksheet.cell(row_index, header.columns[field]).value
                for field in SYNC_FIELDS
            )
            if not any(value not in (None, "") for value in values):
                continue
            sqt = parse_sqt(values[0])
            if sqt is None:
                conflicts.append(
                    SyncConflict(
                        conflict_id=_stable_id(
                            "invalid-sqt",
                            source_fingerprint,
                            worksheet.title,
                            row_index,
                        ),
                        conflict_type=ConflictType.INVALID_SQT,
                        message=f"SQT không hợp lệ tại dòng {row_index}.",
                        source_sheet=worksheet.title,
                        source_row=row_index,
                        container=(
                            str(values[2]) if values[2] is not None else None
                        ),
                        allowed_actions=(
                            ResolutionAction.SKIP_INVALID,
                            ResolutionAction.CANCEL_ALL,
                        ),
                        default_action=ResolutionAction.SKIP_INVALID,
                    )
                )
                continue
            if sqt <= last_sqt:
                continue
            duplicate_key = (
                sqt,
                self._key(values[2]),
                self._key(values[4]),
                self._key(values[3]),
                self._key(values[1]),
            )
            rows.append(
                SyncRow(
                    source_sheet=worksheet.title,
                    source_row=row_index,
                    month=month,
                    sqt=sqt,
                    values=values,
                    duplicate_key=duplicate_key,
                )
            )
        counts = Counter(row.duplicate_key for row in rows)
        for key, count in counts.items():
            if count < 2:
                continue
            first = next(row for row in rows if row.duplicate_key == key)
            conflicts.append(
                SyncConflict(
                    conflict_id=_stable_id(
                        "duplicate", source_fingerprint, worksheet.title, key
                    ),
                    conflict_type=ConflictType.DUPLICATE_SOURCE_ROW,
                    message=f"Có {count} dòng nguồn trùng hoàn toàn (SQT {first.sqt}).",
                    source_sheet=worksheet.title,
                    source_row=first.source_row,
                    sqt=first.sqt,
                    container=(
                        str(first.container) if first.container is not None else None
                    ),
                    allowed_actions=(
                        ResolutionAction.KEEP_ONE,
                        ResolutionAction.KEEP_ALL,
                        ResolutionAction.CANCEL_ALL,
                    ),
                    default_action=ResolutionAction.KEEP_ONE,
                    details={"duplicate_key": key, "count": count},
                )
            )
        return rows, conflicts

    def _resolve_target_headers(self, worksheet: Worksheet) -> HeaderResolution:
        resolution = self.headers.resolve(
            worksheet, SOURCE_HEADER_ALIASES, required=SYNC_FIELDS
        )
        wrong = {
            field: (resolution.columns[field], expected)
            for field, expected in TARGET_EXPECTED_COLUMNS.items()
            if resolution.columns[field] != expected
        }
        if wrong:
            details = ", ".join(
                f"{field}: cột {actual}, cần {expected}"
                for field, (actual, expected) in wrong.items()
            )
            raise HeaderResolutionError(
                f"Header sheet BK không đúng vị trí A–K/P ({details})."
            )
        return resolution

    @staticmethod
    def _last_sqt(worksheet: Worksheet, header: HeaderResolution) -> int:
        values = (
            parse_sqt(worksheet.cell(row, header.columns["sqt"]).value)
            for row in range(header.row_end + 1, worksheet.max_row + 1)
        )
        return max((value for value in values if value is not None), default=0)

    @staticmethod
    def _last_data_row(
        worksheet: Worksheet, header: HeaderResolution
    ) -> int:
        columns = tuple(TARGET_EXPECTED_COLUMNS.values())
        for row in range(worksheet.max_row, header.row_end, -1):
            if any(
                worksheet.cell(row, column).value not in (None, "")
                for column in columns
            ):
                return row
        return header.row_end

    def _create_month_sheet(
        self, workbook: Any, month: int, year: int, target_name: str
    ) -> Worksheet:
        template_name = self.months.nearest_previous_template(
            workbook.sheetnames, month, year
        )
        if template_name is None:
            raise DailySyncError(
                f"Không có sheet tháng trước làm mẫu cho {target_name}."
            )
        template = workbook[template_name]
        header = self._resolve_target_headers(template)
        if self._last_data_row(template, header) <= header.row_end:
            raise DailySyncError(f"Sheet mẫu {template_name} không có dòng dữ liệu.")
        worksheet = workbook.copy_worksheet(template)
        worksheet.title = target_name
        # openpyxl's copy_worksheet omits a few worksheet-level collections.
        for attribute in (
            "freeze_panes",
            "sheet_format",
            "sheet_properties",
            "page_margins",
            "page_setup",
            "print_options",
            "auto_filter",
            "data_validations",
        ):
            try:
                setattr(worksheet, attribute, copy.copy(getattr(template, attribute)))
            except (AttributeError, TypeError):
                pass
        for row in worksheet.iter_rows(
            min_row=header.row_end + 1,
            max_row=worksheet.max_row,
            max_col=worksheet.max_column,
        ):
            for cell in row:
                if isinstance(cell, MergedCell):
                    continue
                cell.value = None
                cell.comment = None
        return worksheet

    @staticmethod
    def _copy_row_style(
        worksheet: Worksheet, source_row: int, target_row: int
    ) -> None:
        if source_row <= 0:
            return
        worksheet.row_dimensions[target_row].height = (
            worksheet.row_dimensions[source_row].height
        )
        for column in range(1, worksheet.max_column + 1):
            source = worksheet.cell(source_row, column)
            target = worksheet.cell(target_row, column)
            if source.has_style:
                target._style = copy.copy(source._style)
            if source.number_format:
                target.number_format = source.number_format

    @staticmethod
    def _worksheet_snapshot(worksheet: Worksheet) -> dict[tuple[int, int], Any]:
        return {
            (row, column): worksheet.cell(row, column).value
            for row in range(1, worksheet.max_row + 1)
            for column in range(1, worksheet.max_column + 1)
        }

    def _verify_saved_sync(
        self,
        path: Path,
        sheet_name: str,
        old_snapshot: Mapping[tuple[int, int], Any],
        append_at: int,
        rows: Sequence[SyncRow],
        *,
        created: bool,
    ) -> None:
        workbook = self.gateway.load(path, read_only=False)
        try:
            if sheet_name not in workbook.sheetnames:
                raise DailySyncError("Bản lưu thiếu sheet đích.")
            worksheet = workbook[sheet_name]
            for coordinate, old_value in old_snapshot.items():
                row, column = coordinate
                if row >= append_at and column in TARGET_EXPECTED_COLUMNS.values():
                    continue
                if worksheet.cell(row, column).value != old_value:
                    raise DailySyncError(
                        f"Ô cũ {worksheet.cell(row, column).coordinate} bị thay đổi."
                    )
            actual = [
                parse_sqt(worksheet.cell(append_at + offset, 1).value)
                for offset in range(len(rows))
            ]
            expected = [row.sqt for row in rows]
            if actual != expected:
                raise DailySyncError("Thứ tự SQT sau khi lưu không đúng.")
        finally:
            workbook.close()

    @staticmethod
    def _key(value: Any) -> Any:
        if isinstance(value, str):
            return " ".join(value.split()).casefold()
        return value

    def _selected_month(
        self, plan: SyncPlan, resolutions: Mapping[str, Any]
    ) -> int | None:
        if plan.selected_month is not None:
            return plan.selected_month
        for conflict in plan.conflicts:
            if conflict.conflict_type is not ConflictType.TARGET_MONTH_AMBIGUOUS:
                continue
            value = resolutions.get(conflict.conflict_id)
            if value is None:
                continue
            action = self._action(value)
            if action in {ResolutionAction.CANCEL, ResolutionAction.CANCEL_ALL}:
                raise DailySyncError("Người dùng đã hủy đồng bộ.")
            month = getattr(value, "selected_month", None)
            if isinstance(value, Mapping):
                month = value.get("selected_month", month)
            if action is ResolutionAction.SELECT_MONTH and month is not None:
                return int(month)
        return None

    def _resolved_rows(
        self,
        plan: SyncPlan,
        month: int,
        resolutions: Mapping[str, Any],
    ) -> tuple[list[SyncRow], int]:
        rows = list(plan.rows_by_month.get(month, ()))
        skipped = 0
        for conflict in plan.conflicts:
            if (
                conflict.conflict_type is ConflictType.INVALID_SQT
                and conflict.source_sheet
                != next(
                    (
                        candidate.source_sheet
                        for candidate in plan.month_candidates
                        if candidate.month == month
                    ),
                    None,
                )
            ):
                continue
            value = resolutions.get(conflict.conflict_id)
            action = (
                self._action(value)
                if value is not None
                else conflict.default_action
            )
            if action in {ResolutionAction.CANCEL, ResolutionAction.CANCEL_ALL}:
                raise DailySyncError("Người dùng đã hủy đồng bộ.")
            if conflict.conflict_type is ConflictType.INVALID_SQT:
                skipped += 1
            elif conflict.conflict_type is ConflictType.DUPLICATE_SOURCE_ROW:
                key = tuple(conflict.details.get("duplicate_key", ()))
                matching = [row for row in rows if row.duplicate_key == key]
                if action is ResolutionAction.KEEP_ONE and len(matching) > 1:
                    keep = matching[0]
                    rows = [
                        row
                        for row in rows
                        if row.duplicate_key != key or row is keep
                    ]
                    skipped += len(matching) - 1
        return rows, skipped

    @staticmethod
    def _action(value: Any) -> ResolutionAction:
        if isinstance(value, (ResolutionAction, str)):
            return ResolutionAction(value)
        action = getattr(value, "action", None)
        if isinstance(value, Mapping):
            action = value.get("action", action)
        return ResolutionAction(action)

    def _create_run(self, source: Path, target: Path) -> int | None:
        if self.run_repository is None:
            return None
        record = self.run_repository.create_run(
            operation=ExcelOperation.DAILY_SYNC,
            source_path=source,
            target_path=target,
            status=ExcelRunStatus.ANALYZING,
        )
        return int(getattr(record, "id", record))

    def _update_run(self, run_id: int | None, **changes: Any) -> None:
        if self.run_repository is not None and run_id is not None:
            self.run_repository.update_run(run_id, **changes)

    def _finish_result(self, result: SyncResult) -> None:
        if self.run_repository is None or result.run_id is None:
            return
        self.run_repository.finish_run(
            result.run_id,
            status=result.status,
            sheet_name=result.sheet_name,
            backup_path=result.backup_path,
            target_fingerprint_after=result.fingerprint_after,
            total_items=result.added_rows + result.skipped_rows,
            changed_items=result.added_rows,
            skipped_items=result.skipped_rows,
            conflict_count=result.conflict_count,
        )

    def _finish_failed(self, run_id: int | None, exc: Exception) -> None:
        if self.run_repository is None or run_id is None:
            return
        cancelled = "người dùng đã hủy" in str(exc).casefold()
        self.run_repository.finish_run(
            run_id,
            status=(
                ExcelRunStatus.CANCELLED
                if cancelled
                else ExcelRunStatus.FAILED
            ),
            error_message=None if cancelled else str(exc),
        )

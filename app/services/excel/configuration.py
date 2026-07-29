"""Read-only validation of the Step 3 workbook configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.services.file_stability import FileStabilityChecker

from .daily_sync import SOURCE_HEADER_ALIASES, SYNC_FIELDS
from .headers import HeaderResolver
from .resolvers import MonthSheetService, YearResolver
from .workbook import (
    ExcelLockService,
    WorkbookGateway,
    ensure_supported_workbook,
)


@dataclass(frozen=True, slots=True)
class ConfigurationCheck:
    name: str
    ok: bool
    message: str


@dataclass(slots=True)
class ConfigurationValidationResult:
    checks: list[ConfigurationCheck] = field(default_factory=list)
    source_year: int | None = None
    target_year: int | None = None

    @property
    def is_valid(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks)

    @property
    def errors(self) -> list[str]:
        return [check.message for check in self.checks if not check.ok]


class ExcelConfigurationService:
    def __init__(
        self,
        settings: Any | None = None,
        *,
        daily_path: str | Path | None = None,
        bk_path: str | Path | None = None,
        temp_dir: str | Path | None = None,
        gateway: WorkbookGateway | None = None,
        lock_service: ExcelLockService | None = None,
        stability_checker: FileStabilityChecker | None = None,
        header_resolver: HeaderResolver | None = None,
        month_service: MonthSheetService | None = None,
        year_resolver: YearResolver | None = None,
    ) -> None:
        paths = getattr(settings, "paths", None)
        self.daily_path = Path(
            daily_path or getattr(settings, "daily_workbook_path", "")
        )
        self.bk_path = Path(
            bk_path or getattr(settings, "bk_workbook_path", "")
        )
        system_dir = getattr(paths, "system_dir", Path("Output") / "_system")
        self.temp_dir = Path(
            temp_dir
            or getattr(paths, "excel_temp_dir", system_dir / "Excel" / "Temp")
        )
        self.gateway = gateway or WorkbookGateway()
        self.lock_service = lock_service or ExcelLockService()
        self.stability_checker = stability_checker or FileStabilityChecker()
        self.headers = header_resolver or HeaderResolver()
        self.months = month_service or MonthSheetService()
        self.years = year_resolver or YearResolver()

    def validate(
        self, progress_callback: Callable[[str], None] | None = None
    ) -> ConfigurationValidationResult:
        result = ConfigurationValidationResult()

        def progress(message: str) -> None:
            if progress_callback is not None:
                progress_callback(message)

        source_book = None
        target_book = None
        snapshot: Path | None = None
        try:
            progress("Đang kiểm tra file Hàng ngày…")
            source = ensure_supported_workbook(self.daily_path)
            if not source.is_file():
                raise FileNotFoundError(f"Không tìm thấy file Hàng ngày: {source}")
            self.stability_checker.wait(source)
            self.lock_service.ensure_readable(source)
            snapshot = self.gateway.source_snapshot(source, self.temp_dir)
            source_book = self.gateway.load(snapshot, read_only=True)
            daily_sheets = self.months.daily_sheets(source_book.sheetnames)
            if not daily_sheets:
                raise ValueError("Không có sheet Tháng 1…Tháng 12.")
            header_ok = False
            header_errors: list[str] = []
            for sheet_name in daily_sheets.values():
                try:
                    self.headers.resolve(
                        source_book[sheet_name],
                        SOURCE_HEADER_ALIASES,
                        required=SYNC_FIELDS,
                    )
                    header_ok = True
                    break
                except Exception as exc:
                    header_errors.append(f"{sheet_name}: {exc}")
            if not header_ok:
                raise ValueError(
                    "Không nhận diện được header nguồn: " + "; ".join(header_errors)
                )
            result.checks.append(
                ConfigurationCheck(
                    "daily_workbook",
                    True,
                    "File Hàng ngày đọc được và có cấu trúc phù hợp.",
                )
            )
        except Exception as exc:
            result.checks.append(
                ConfigurationCheck("daily_workbook", False, str(exc))
            )
        finally:
            if source_book is not None:
                source_book.close()
            if snapshot is not None:
                snapshot.unlink(missing_ok=True)

        try:
            progress("Đang kiểm tra file BK…")
            target = ensure_supported_workbook(self.bk_path)
            if not target.is_file():
                raise FileNotFoundError(f"Không tìm thấy file BK: {target}")
            # The probe creates and removes a sibling temp file; it never saves
            # or changes the workbook itself.
            with self.lock_service.acquire(target):
                pass
            target_book = self.gateway.load(target, read_only=False)
            target_sheets = [
                name
                for name in target_book.sheetnames
                if self.months.parse_target_sheet(name) is not None
            ]
            if not target_sheets:
                raise ValueError("Không có sheet BK dạng TMM YY.")
            header_ok = False
            header_errors: list[str] = []
            for sheet_name in target_sheets:
                try:
                    self.headers.resolve(
                        target_book[sheet_name],
                        SOURCE_HEADER_ALIASES,
                        required=SYNC_FIELDS,
                    )
                    header_ok = True
                    break
                except Exception as exc:
                    header_errors.append(f"{sheet_name}: {exc}")
            if not header_ok:
                raise ValueError(
                    "Không nhận diện được header BK: " + "; ".join(header_errors)
                )
            result.checks.append(
                ConfigurationCheck(
                    "bk_workbook",
                    True,
                    "File BK đọc được, có sheet tháng và có quyền ghi.",
                )
            )
        except Exception as exc:
            result.checks.append(ConfigurationCheck("bk_workbook", False, str(exc)))
        finally:
            if target_book is not None:
                target_book.close()

        return result

    validate_configuration = validate


def validate_configuration(
    settings: Any | None = None, **kwargs: Any
) -> ConfigurationValidationResult:
    return ExcelConfigurationService(settings, **kwargs).validate()

"""Month sheet and workbook year naming rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .headers import normalize_header


_DAILY_SHEET_RE = re.compile(r"^thang\s*(1[0-2]|[1-9])$")
_TARGET_SHEET_RE = re.compile(
    r"^t\s*0?(1[0-2]|[1-9])\s*[-_/ ]\s*(\d{2}|\d{4})$",
    re.IGNORECASE,
)
_PAYMENT_SHEET_RE = re.compile(
    r"^T(0[1-9]|1[0-2]) (\d{2}) (HP|NAM)$",
    re.IGNORECASE,
)
_YEAR_TOKEN_RE = re.compile(r"(?<!\d)((?:19|20|21)\d{2})(?!\d)")


class YearResolutionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PaymentSheetName:
    month: int
    year: int
    sheet_type: str


class MonthSheetService:
    def parse_daily_sheet(self, name: str) -> int | None:
        match = _DAILY_SHEET_RE.fullmatch(normalize_header(name))
        return int(match.group(1)) if match else None

    def parse_target_sheet(self, name: str) -> tuple[int, int] | None:
        match = _TARGET_SHEET_RE.fullmatch(str(name).strip())
        if match is None:
            return None
        year_text = match.group(2)
        year = int(year_text)
        if len(year_text) == 2:
            year += 2000
        return int(match.group(1)), year

    def parse_payment_sheet(self, name: str) -> PaymentSheetName | None:
        """Parse only exact ``TMM YY HP|NAM`` payment sheet names.

        Leading/trailing whitespace and case are ignored. Archive/copy suffixes
        are rejected because the regular expression must match the whole name.
        """

        match = _PAYMENT_SHEET_RE.fullmatch(str(name).strip())
        if match is None:
            return None
        year_text = match.group(2)
        year = int(year_text) + 2000
        return PaymentSheetName(int(match.group(1)), year, match.group(3).upper())

    def payment_sheets(
        self,
        sheet_names: Iterable[str],
        *,
        year: int | None = None,
        sheet_type: str | None = None,
    ) -> dict[tuple[int, int, str], str]:
        result: dict[tuple[int, int, str], str] = {}
        expected_type = sheet_type.upper() if sheet_type else None
        for name in sheet_names:
            parsed = self.parse_payment_sheet(name)
            if parsed is None:
                continue
            if year is not None and parsed.year != year:
                continue
            if expected_type is not None and parsed.sheet_type != expected_type:
                continue
            key = (parsed.month, parsed.year, parsed.sheet_type)
            if key in result:
                raise ValueError(
                    f"Có nhiều sheet Thanh toán {parsed.sheet_type} cho "
                    f"tháng {parsed.month:02d}/{parsed.year}."
                )
            result[key] = name
        return result

    def find_payment_sheet(
        self,
        sheet_names: Iterable[str],
        month: int,
        year: int,
        sheet_type: str,
    ) -> str | None:
        return self.payment_sheets(sheet_names).get(
            (month, year, sheet_type.upper())
        )

    @staticmethod
    def payment_target_name(month: int, year: int, sheet_type: str) -> str:
        normalized_type = sheet_type.upper()
        if month not in range(1, 13):
            raise ValueError("Tháng phải từ 1 đến 12.")
        if normalized_type not in {"HP", "NAM"}:
            raise ValueError("Loại sheet Thanh toán phải là HP hoặc NAM.")
        return f"T{month:02d} {year % 100:02d} {normalized_type}"

    def nearest_previous_payment_template(
        self,
        sheet_names: Iterable[str],
        month: int,
        year: int,
        sheet_type: str,
    ) -> str | None:
        expected_type = sheet_type.upper()
        candidates: list[tuple[int, int, str]] = []
        seen: set[tuple[int, int]] = set()
        for name in sheet_names:
            parsed = self.parse_payment_sheet(name)
            if parsed is None or parsed.sheet_type != expected_type:
                continue
            period = (parsed.year, parsed.month)
            if period >= (year, month):
                continue
            if period in seen:
                raise ValueError(
                    f"Có nhiều sheet {expected_type} cho tháng "
                    f"{parsed.month:02d}/{parsed.year}."
                )
            seen.add(period)
            candidates.append((parsed.year, parsed.month, name))
        return max(candidates)[2] if candidates else None

    def daily_sheets(self, sheet_names: Iterable[str]) -> dict[int, str]:
        result: dict[int, str] = {}
        for name in sheet_names:
            month = self.parse_daily_sheet(name)
            if month is None:
                continue
            if month in result:
                raise ValueError(f"Có nhiều sheet nguồn cho tháng {month}.")
            result[month] = name
        return result

    def target_sheets(
        self, sheet_names: Iterable[str], *, year: int | None = None
    ) -> dict[int, str]:
        result: dict[int, str] = {}
        for name in sheet_names:
            parsed = self.parse_target_sheet(name)
            if parsed is None:
                continue
            month, sheet_year = parsed
            if year is not None and sheet_year != year:
                continue
            if month in result:
                raise ValueError(
                    f"Có nhiều sheet BK cho tháng {month}/{sheet_year}."
                )
            result[month] = name
        return result

    @staticmethod
    def target_name(month: int, year: int) -> str:
        if month not in range(1, 13):
            raise ValueError("Tháng phải từ 1 đến 12.")
        return f"T{month:02d} {year % 100:02d}"

    def nearest_previous_template(
        self, sheet_names: Iterable[str], month: int, year: int
    ) -> str | None:
        sheets = self.target_sheets(sheet_names, year=year)
        previous = [candidate for candidate in sheets if candidate < month]
        return sheets[max(previous)] if previous else None


class YearResolver:
    def from_filename(self, path: str | Path) -> int:
        years = {int(value) for value in _YEAR_TOKEN_RE.findall(Path(path).stem)}
        if len(years) != 1:
            reason = "không có" if not years else "có nhiều"
            raise YearResolutionError(
                f"Tên file {Path(path).name!r} {reason} năm bốn chữ số rõ ràng."
            )
        return years.pop()

    def from_target_sheets(self, sheet_names: Iterable[str]) -> int:
        parser = MonthSheetService()
        years = {
            parsed[1]
            for name in sheet_names
            if (parsed := parser.parse_target_sheet(name)) is not None
        }
        if len(years) != 1:
            reason = "không có" if not years else "không nhất quán"
            raise YearResolutionError(f"Năm trong tên sheet BK {reason}.")
        return years.pop()

    def target_year(
        self, path: str | Path, sheet_names: Iterable[str]
    ) -> int:
        years = {
            int(value)
            for value in _YEAR_TOKEN_RE.findall(Path(path).stem)
        }
        if len(years) == 1:
            return years.pop()
        if len(years) > 1:
            raise YearResolutionError(
                f"Tên file {Path(path).name!r} có nhiều năm bốn chữ số."
            )
        return self.from_target_sheets(sheet_names)

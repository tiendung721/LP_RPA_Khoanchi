"""Chuẩn hóa dữ liệu người dùng nhập và kiểm tra toàn bộ lô JSON."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from app.constants import (
    CONTAINER_PATTERN,
    FEE_CODES,
    RULE_CODES,
    SCHEMA_VERSION,
)
from app.models import (
    BatchDocument,
    DataRow,
    RowValidation,
    Severity,
    ValidationIssue,
    ValidationResult,
    ValidationSummary,
)
from app.schema import SchemaError, parse_document

_CONTAINER_RE = re.compile(CONTAINER_PATTERN)
_CONTAINER_SEPARATORS_RE = re.compile(r"[\s\-_–—]+", flags=re.UNICODE)
_COLLAPSE_WHITESPACE_RE = re.compile(r"\s+", flags=re.UNICODE)
_AMOUNT_ALLOWED_RE = re.compile(r"^[0-9][0-9.,\s]*$", flags=re.UNICODE)
_AMOUNT_GROUPED_RE = re.compile(r"^[0-9]{1,3}(?:([.,\s])[0-9]{3})(?:\1[0-9]{3})*$")
_MAX_SIGNED_64 = 9_223_372_036_854_775_807


class AmountParseError(ValueError):
    """Số tiền người dùng nhập không thể chuẩn hóa an toàn."""


def normalize_container(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("Container phải là chuỗi hoặc để trống.")
    normalized = _CONTAINER_SEPARATORS_RE.sub("", value.strip().upper())
    return normalized or None


def normalize_bl(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("B/L phải là chuỗi hoặc để trống.")
    normalized = _COLLAPSE_WHITESPACE_RE.sub(" ", value.strip()).upper()
    return normalized or None


def normalize_fee(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("Mã loại cước phải là chuỗi.")
    normalized = value.strip().upper()
    if normalized not in FEE_CODES:
        raise ValueError("Mã loại cước không thuộc danh mục chính thức.")
    return normalized


def normalize_rule(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("Mã xử lý tiền phải là chuỗi hoặc để trống.")
    normalized = value.strip().upper()
    if not normalized:
        return None
    if normalized not in RULE_CODES:
        raise ValueError("Mã xử lý tiền không thuộc danh mục chính thức.")
    return normalized


def parse_amount(value: int | str | None) -> int | None:
    """Parse số nguyên VND; không suy đoán ký hiệu thập phân."""

    if value is None:
        return None
    if isinstance(value, bool):
        raise AmountParseError("Số tiền không được là kiểu boolean.")
    if type(value) is int:
        if value < 0:
            raise AmountParseError("Số tiền không được âm.")
        if value > _MAX_SIGNED_64:
            raise AmountParseError("Số tiền vượt giới hạn số nguyên 64 bit.")
        return value
    if not isinstance(value, str):
        raise AmountParseError("Số tiền phải là số nguyên hoặc để trống.")

    text = value.strip()
    if not text:
        return None
    if not _AMOUNT_ALLOWED_RE.fullmatch(text):
        raise AmountParseError(
            "Số tiền chỉ được chứa chữ số và dấu phân cách hàng nghìn."
        )
    if text.isdigit():
        parsed = int(text)
    else:
        # Thu gọn mọi dạng khoảng trắng thành dấu cách trước khi kiểm tra nhóm.
        grouped = _COLLAPSE_WHITESPACE_RE.sub(" ", text)
        match = _AMOUNT_GROUPED_RE.fullmatch(grouped)
        if match is None:
            raise AmountParseError(
                "Dấu phân cách tiền không đúng nhóm hàng nghìn."
            )
        parsed = int(re.sub(r"[.,\s]", "", grouped))
    if parsed > _MAX_SIGNED_64:
        raise AmountParseError("Số tiền vượt giới hạn số nguyên 64 bit.")
    return parsed


class ValidationService:
    """Kiểm tra schema, kiểu trường, quan hệ nghiệp vụ và cảnh báo."""

    def normalize_row(
        self,
        row: DataRow | None = None,
        *,
        cont: str | None = None,
        bl: str | None = None,
        fee: str | None = None,
        rule: str | None = None,
        amount: int | str | None = None,
    ) -> DataRow:
        if row is not None:
            cont = row.cont
            bl = row.bl
            fee = row.fee
            rule = row.rule
            amount = row.amount
        if fee is None:
            raise ValueError("Vui lòng chọn mã loại cước.")
        return DataRow(
            cont=normalize_container(cont),
            bl=normalize_bl(bl),
            fee=normalize_fee(fee),
            rule=normalize_rule(rule),
            amount=parse_amount(amount),
        )

    def validate_row(self, row: DataRow, index: int = 0) -> RowValidation:
        issues: list[ValidationIssue] = []

        def error(code: str, message: str, field: str) -> None:
            issues.append(
                ValidationIssue(Severity.ERROR, code, message, index, field)
            )

        def warning(code: str, message: str, field: str | None = None) -> None:
            issues.append(
                ValidationIssue(Severity.WARNING, code, message, index, field)
            )

        cont_valid_type = row.cont is None or isinstance(row.cont, str)
        bl_valid_type = row.bl is None or isinstance(row.bl, str)
        fee_valid = isinstance(row.fee, str) and row.fee in FEE_CODES
        rule_valid = row.rule is None or (
            isinstance(row.rule, str) and row.rule in RULE_CODES
        )
        amount_valid_type = row.amount is None or type(row.amount) is int

        if not cont_valid_type:
            error(
                "cont_type",
                "Container phải là chuỗi hoặc null.",
                "cont",
            )
        elif isinstance(row.cont, str) and not _CONTAINER_RE.fullmatch(row.cont):
            warning(
                "cont_format",
                "Container chưa đúng mẫu 4 chữ cái và 7 chữ số.",
                "cont",
            )

        if not bl_valid_type:
            error("bl_type", "B/L phải là chuỗi hoặc null.", "bl")

        if not fee_valid:
            error(
                "fee_unknown",
                "Mã loại cước không thuộc danh mục chính thức.",
                "fee",
            )

        if not rule_valid:
            error(
                "rule_unknown",
                "Mã xử lý tiền phải là HD, ST, CV, GV hoặc null.",
                "rule",
            )

        if not amount_valid_type:
            if isinstance(row.amount, bool):
                message = "Số tiền không được là kiểu boolean."
                code = "amount_boolean"
            else:
                message = "Số tiền phải là số nguyên hoặc null."
                code = "amount_type"
            error(code, message, "amount")
        elif isinstance(row.amount, int) and row.amount < 0:
            error("amount_negative", "Số tiền không được âm.", "amount")

        if fee_valid and rule_valid:
            if row.rule == "HD" and row.fee != "CB":
                error(
                    "hd_requires_cb",
                    "Quy tắc HD chỉ được dùng cho loại cước CB.",
                    "rule",
                )
            if row.fee == "CB" and row.rule != "HD":
                error(
                    "cb_requires_hd",
                    "Loại cước CB bắt buộc dùng quy tắc HD.",
                    "rule",
                )

        if cont_valid_type and bl_valid_type and row.cont is None and row.bl is None:
            warning(
                "missing_reference",
                "Cả container và B/L đều chưa được xác định.",
            )
        if row.fee == "CXD":
            warning(
                "fee_cxd",
                "Loại cước CXD cần được người dùng kiểm tra lại.",
                "fee",
            )
        if amount_valid_type and row.amount is None:
            warning(
                "amount_missing",
                "Số tiền chưa được xác định.",
                "amount",
            )
        elif amount_valid_type and row.amount == 0:
            warning(
                "amount_zero",
                "Số tiền đang bằng 0.",
                "amount",
            )
        if rule_valid and row.rule is None:
            warning(
                "rule_missing",
                "Quy tắc xử lý tiền chưa được xác định.",
                "rule",
            )
        if (
            fee_valid
            and row.fee == "CB"
            and bl_valid_type
            and row.bl is None
        ):
            warning(
                "cb_missing_bl",
                "Dòng cước biển chưa có B/L.",
                "bl",
            )
        return RowValidation(row_index=index, issues=issues)

    def validate_document(self, value: BatchDocument | object) -> ValidationResult:
        if isinstance(value, BatchDocument):
            document = value
            if type(document.v) is not int or document.v != SCHEMA_VERSION:
                issue = ValidationIssue(
                    Severity.ERROR,
                    "invalid_version",
                    "Khóa v phải là số nguyên 1.",
                    field="v",
                )
                return ValidationResult(
                    issues=[issue],
                    summary=ValidationSummary(total_rows=len(document.rows)),
                )
        else:
            try:
                document = parse_document(value)
            except SchemaError as exc:
                issue = ValidationIssue(
                    Severity.ERROR,
                    exc.code,
                    str(exc),
                    exc.row_index,
                    exc.field,
                )
                return ValidationResult(issues=[issue])

        row_results = [
            self.validate_row(row, index) for index, row in enumerate(document.rows)
        ]
        self._append_duplicate_warnings(document.rows, row_results)
        all_issues = [
            issue for row_result in row_results for issue in row_result.issues
        ]

        statuses = [result.status for result in row_results]
        fee_counts: Counter[str] = Counter()
        container_count = 0
        bl_count = 0
        amount_count = 0
        total_amount = 0
        for row in document.rows:
            if isinstance(row.cont, str) and bool(row.cont):
                container_count += 1
            if isinstance(row.bl, str) and bool(row.bl):
                bl_count += 1
            if type(row.amount) is int and row.amount >= 0:
                amount_count += 1
                total_amount += row.amount
            if isinstance(row.fee, str):
                fee_counts[row.fee] += 1

        summary = ValidationSummary(
            total_rows=len(document.rows),
            valid_count=statuses.count(Severity.VALID),
            warning_count=statuses.count(Severity.WARNING),
            error_count=statuses.count(Severity.ERROR),
            container_count=container_count,
            bl_count=bl_count,
            amount_count=amount_count,
            total_amount=total_amount,
            fee_counts=dict(sorted(fee_counts.items())),
        )
        return ValidationResult(
            issues=all_issues,
            row_results=row_results,
            summary=summary,
        )

    @staticmethod
    def _append_duplicate_warnings(
        rows: Sequence[DataRow],
        results: Sequence[RowValidation],
    ) -> None:
        positions: dict[str, list[int]] = {}
        for index, row in enumerate(rows):
            # JSON tạo khóa ổn định cả khi một trường đầu vào sai kiểu/unhashable.
            try:
                key = json.dumps(
                    row.to_list(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            except (TypeError, ValueError):
                key = repr(row.to_list())
            positions.setdefault(key, []).append(index)
        for duplicate_indices in positions.values():
            if len(duplicate_indices) < 2:
                continue
            display_rows = ", ".join(str(index + 1) for index in duplicate_indices)
            for index in duplicate_indices:
                results[index].issues.append(
                    ValidationIssue(
                        Severity.WARNING,
                        "duplicate_row",
                        f"Dòng trùng hoàn toàn với các dòng: {display_rows}.",
                        row_index=index,
                    )
                )


def validate_document(value: BatchDocument | Mapping[str, Any]) -> ValidationResult:
    return ValidationService().validate_document(value)


def validate_row(row: DataRow, index: int = 0) -> RowValidation:
    return ValidationService().validate_row(row, index)

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill

from app.services.excel.models import ExcelRunStatus
from app.services.excel.payment_sync import (
    SUMMARY_HEADERS,
    PaymentSyncError,
    PaymentSyncService,
)


class _ImmediateStabilityChecker:
    def wait(self, _path: str | Path) -> None:
        return None


def _save_bk(
    path: Path,
    *,
    month: int,
    include_data: bool = True,
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = f"T{month:02d} 26"
    headers = [
        "SQT",
        "Số Container",
        "Cước biển",
        "Cước bộ đóng hàng",
        "Nâng vỏ",
        "Hạ Hàng",
        "Nâng Hàng",
        "Hạ vỏ",
        "Cước VTN",
        "Lưu cont",
        "Quá tải",
        "VS + D/O",
        "Hóa đơn VS",
        "LÀM LỆNH",
        "SỬA CHỮA",
        *SUMMARY_HEADERS,
    ]
    for column, value in enumerate(headers, 1):
        sheet.cell(1, column).value = value
    if include_data:
        values = [
            601,
            "CONT0000001",
            7_000_000,
            3_000_000,
            100_000,
            200_000,
            300_000,
            400_000,
            5_000_000,
            600_000,
            700_000,
            800_000,
            None,
            150_000,
            900_000,
        ]
        for column, value in enumerate(values, 1):
            sheet.cell(2, column).value = value
    workbook.save(path)
    workbook.close()


def _save_payment_template(path: Path, *, month: int = 5) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = f"T{month:02d} 26"
    sheet.merge_cells("A5:H5")
    sheet["A4"] = "Hải Phòng, Ngày       tháng       năm 2026"
    sheet["A5"] = f"BẢNG KÊ TẠM ỨNG NÂNG HẠ THÁNG {month:02d}/26"
    headers = {
        1: "QT",
        2: "TUYẾN ĐƯỜNG",
        4: "SỐ CONT",
        5: "NÂNG VỎ",
        7: "HẠ HÀNG",
        9: "Cước bộ",
        10: "Cước biển",
        11: "Cước bộ",
        13: "NÂNG HÀNG",
        15: "HẠ VỎ",
        17: "VS + D/O",
        19: "LÀM LỆNH",
        20: "Lưu Cont",
        22: "Sửa chữa Cont",
        24: "QUÁ TẢI",
    }
    for offset, value in enumerate(SUMMARY_HEADERS, 26):
        headers[offset] = value
    for column, value in headers.items():
        sheet.cell(7, column).value = value

    sheet["A8"] = 500
    sheet["D8"] = "OLDCONT0001"
    sheet["G8"] = 999
    sheet["Z8"] = "=A8"
    sheet["AB8"] = "=E8+G8"
    sheet["AD8"] = "=M8+O8+Q8+S8"
    sheet["AF8"] = "=T8"
    sheet["AG8"] = "=V8"
    sheet["AH8"] = "=X8"
    sheet["AI8"] = "=AF8+AH8"
    sheet["E8"].fill = PatternFill("solid", fgColor="FFF2CC")
    sheet["A10"] = "TỔNG TIỀN"
    sheet["E10"] = "=SUM(E8:E9)"
    sheet["G10"] = "=SUBTOTAL(9,G8:G9)"
    sheet["M10"] = "=SUBTOTAL(9,M8:M9)"
    sheet["O10"] = "=SUBTOTAL(9,O8:O9)"
    sheet["Q10"] = "=SUBTOTAL(9,Q8:Q9)"
    sheet["S10"] = "=SUBTOTAL(9,S8:S9)"
    sheet["T10"] = "=SUBTOTAL(9,T8:T9)"
    sheet["V10"] = "=SUBTOTAL(9,V8:V9)"
    sheet["X10"] = "=SUBTOTAL(9,X8:X9)"
    sheet["G12"] = "Người Duyệt"
    sheet["U12"] = "Người làm tạm ứng"
    sheet["A15"] = "Số tiền thanh toán"
    sheet["D16"] = "Dữ liệu tháng cũ"
    sheet["AN16"] = 123
    sheet["XFD1"].fill = PatternFill("solid", fgColor="FFFFFF")
    sheet.freeze_panes = "A8"
    sheet.auto_filter.ref = "A7:XFD9"
    workbook.save(path)
    workbook.close()


def _service(
    bk: Path,
    payment: Path,
    runtime_dir: Path,
) -> PaymentSyncService:
    return PaymentSyncService(
        bk_path=bk,
        payment_path=payment,
        temp_dir=runtime_dir / "Temp",
        backup_dir=runtime_dir / "Backup",
        stability_checker=_ImmediateStabilityChecker(),
    )


def test_payment_sync_creates_missing_month_from_previous_clean_template(
    tmp_path: Path,
) -> None:
    bk = tmp_path / "BK 2026.xlsx"
    payment = tmp_path / "Thanh toan 2026.xlsx"
    runtime_dir = tmp_path / "Excel"
    _save_bk(bk, month=6)
    _save_payment_template(payment, month=5)
    service = _service(bk, payment, runtime_dir)

    plan = service.analyze(source_sheet_name="T06 26")

    assert plan.target_sheet == "T06 26"
    assert plan.target_sheet_created
    assert plan.template_sheet == "T05 26"
    assert plan.new_count == 1
    assert plan.has_changes

    result = service.apply(plan, {})

    assert result.status is ExcelRunStatus.SUCCEEDED
    assert result.sheet_created
    assert result.template_sheet_name == "T05 26"
    assert result.inserted_rows == 1
    assert result.backup_path == (
        runtime_dir / "Backup" / "Thanh toan 2026_latest.xlsx"
    )
    assert result.backup_path.is_file()

    workbook = load_workbook(payment, data_only=False)
    try:
        assert workbook.sheetnames == ["T06 26", "T05 26"]
        template = workbook["T05 26"]
        created = workbook["T06 26"]
        assert template["A8"].value == 500
        assert template["D8"].value == "OLDCONT0001"
        assert created["A5"].value.endswith("THÁNG 06/26")
        assert created["A8"].value == 601
        assert created["D8"].value == "CONT0000001"
        assert created["G8"].value == 200_000
        assert created["Z8"].value == "=A8"
        assert created["G10"].value == "=SUBTOTAL(9,G8:G9)"
        assert created["A15"].value is None
        assert created["D16"].value is None
        assert created["AN16"].value is None
        assert created["E8"].fill.fgColor.rgb == template["E8"].fill.fgColor.rgb
        assert created.freeze_panes == "A8"
        assert created.auto_filter.ref == "A7:AN9"
        assert "A5:H5" in {
            str(item) for item in created.merged_cells.ranges
        }
        assert created.max_column < 100
    finally:
        workbook.close()

    second_plan = service.analyze(source_sheet_name="T06 26")
    assert not second_plan.target_sheet_created
    assert second_plan.template_sheet is None
    assert second_plan.new_count == 0
    assert second_plan.unchanged_count == 1


def test_payment_sync_missing_month_requires_a_previous_template(
    tmp_path: Path,
) -> None:
    bk = tmp_path / "BK 2026.xlsx"
    payment = tmp_path / "Thanh toan 2026.xlsx"
    _save_bk(bk, month=5)
    _save_payment_template(payment, month=6)
    service = _service(bk, payment, tmp_path / "Excel")

    with pytest.raises(
        PaymentSyncError,
        match="Không có sheet Thanh toán tháng trước",
    ):
        service.analyze(source_sheet_name="T05 26")


def test_empty_bk_month_still_requires_confirmation_and_creates_sheet(
    tmp_path: Path,
) -> None:
    bk = tmp_path / "BK 2026.xlsx"
    payment = tmp_path / "Thanh toan 2026.xlsx"
    runtime_dir = tmp_path / "Excel"
    _save_bk(bk, month=6, include_data=False)
    _save_payment_template(payment, month=5)
    service = _service(bk, payment, runtime_dir)

    plan = service.analyze(source_sheet_name="T06 26")

    assert plan.target_sheet_created
    assert plan.new_count == 0
    assert plan.requires_user_input

    result = service.apply(plan, {})

    assert result.status is ExcelRunStatus.SUCCEEDED
    assert result.sheet_created
    assert result.inserted_rows == 0
    workbook = load_workbook(payment, read_only=True)
    try:
        assert "T06 26" in workbook.sheetnames
    finally:
        workbook.close()

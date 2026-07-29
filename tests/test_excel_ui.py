from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from app.ui.excel_dialogs import (
    ConflictResolutionDialog,
    ManualRowPickerDialog,
    MonthSelectionDialog,
)
from app.ui.excel_task_controller import ExcelTaskController
from app.ui.settings_page import SettingsPage
from app.ui.workflow_page import WorkflowPage


def test_step_three_has_exactly_two_primary_actions_and_two_statuses(qtbot) -> None:
    page = WorkflowPage()
    qtbot.addWidget(page)

    buttons = page.step3_card.findChildren(QPushButton)
    primary_buttons = [button for button in buttons if button.property("primary")]

    assert primary_buttons == [
        page.sync_daily_button,
        page.post_expenses_button,
    ]
    assert page.sync_daily_button.text() == "Đồng bộ dữ liệu Hàng ngày"
    assert page.post_expenses_button.text() == "Nhập khoản chi vào BK"
    assert page.sync_status_label.text() == "Đồng bộ gần nhất: —"
    assert page.posting_status_label.text() == "Nhập khoản chi gần nhất: —"


def test_step_three_locks_both_actions_while_running(qtbot) -> None:
    page = WorkflowPage()
    qtbot.addWidget(page)

    page.set_excel_running("sync", "Đang đọc file Hàng ngày")

    assert not page.sync_daily_button.isEnabled()
    assert not page.post_expenses_button.isEnabled()
    assert page.sync_daily_button.text() == "Đang đồng bộ…"
    assert "Đang đọc file Hàng ngày" in page.sync_status_label.text()

    page.set_excel_idle("sync")

    assert page.sync_daily_button.isEnabled()
    assert page.post_expenses_button.isEnabled()
    assert page.sync_daily_button.text() == "Đồng bộ dữ liệu Hàng ngày"


def test_settings_round_trip_optional_excel_paths_and_reject_xls(
    qtbot,
    tmp_path: Path,
) -> None:
    bat = tmp_path / "assistant.bat"
    bat.write_text("@echo off", encoding="utf-8")
    daily = tmp_path / "Hang ngay 2026.xlsx"
    bk = tmp_path / "BK 2026.xlsm"
    page = SettingsPage(
        {
            "assistant_bat_path": str(bat),
            "output_dir": str(tmp_path),
            "daily_workbook_path": str(daily),
            "bk_workbook_path": str(bk),
        }
    )
    qtbot.addWidget(page)

    assert page.save_button.isEnabled()
    assert page.settings_data()["daily_workbook_path"] == str(daily)
    assert page.settings_data()["bk_workbook_path"] == str(bk)

    page.daily_workbook_edit.setText(str(tmp_path / "legacy.xls"))

    assert not page.save_button.isEnabled()
    assert ".xlsx hoặc .xlsm" in page.validation_label.text()


class _Service:
    def __init__(self, plan: Any) -> None:
        self.plan = plan
        self.apply_calls: list[tuple[Any, Any]] = []

    def analyze(self, *, progress_callback) -> Any:
        progress_callback("Đang phân tích")
        return self.plan

    def apply(self, plan: Any, resolutions: Any, *, progress_callback) -> Any:
        self.apply_calls.append((plan, resolutions))
        progress_callback("Đang ghi")
        return {"message": "Hoàn tất", "operation": "sync"}


def test_excel_controller_auto_applies_plan_without_conflicts(qtbot) -> None:
    service = _Service({"operation": "sync", "has_changes": True, "conflicts": []})
    controller = ExcelTaskController(daily_sync_service=service)
    completed: list[Any] = []
    progress: list[tuple[str, str]] = []
    controller.completed.connect(completed.append)
    controller.progress.connect(lambda operation, message: progress.append((operation, message)))

    try:
        controller.start_sync()
        qtbot.waitUntil(lambda: bool(completed), timeout=2000)

        assert service.apply_calls
        assert service.apply_calls[0][1] == {}
        assert ("sync", "Đang phân tích") in progress
        assert ("sync", "Đang ghi") in progress
        assert not controller.is_busy
    finally:
        controller.shutdown()


def test_excel_controller_waits_for_aggregate_resolution(qtbot) -> None:
    plan = {
        "operation": "posting",
        "conflicts": [{"conflict_id": "c1", "type": "TARGET_CELL_OCCUPIED"}],
    }
    service = _Service(plan)
    controller = ExcelTaskController(expense_posting_service=service)
    ready: list[Any] = []
    completed: list[Any] = []
    controller.analysis_ready.connect(ready.append)
    controller.completed.connect(completed.append)

    try:
        controller.start_posting()
        qtbot.waitUntil(lambda: bool(ready), timeout=2000)

        assert controller.phase == "waiting_user"
        with pytest.raises(RuntimeError):
            controller.start_sync()

        controller.apply_plan(
            ready[0],
            {"c1": {"conflict_id": "c1", "action": "KEEP_EXISTING"}},
        )
        qtbot.waitUntil(lambda: bool(completed), timeout=2000)

        assert service.apply_calls[0][1]["c1"]["action"] == "KEEP_EXISTING"
    finally:
        controller.shutdown()


def test_excel_controller_refines_selector_before_apply(qtbot) -> None:
    initial = {
        "operation": "posting",
        "conflicts": [{"conflict_id": "row", "type": "BL_ONLY_NO_CONTAINER"}],
    }

    class RefiningService(_Service):
        def __init__(self) -> None:
            super().__init__(initial)
            self.refine_calls: list[Any] = []

        def refine(
            self, plan: Any, resolutions: Any, *, progress_callback
        ) -> Any:
            self.refine_calls.append((plan, resolutions))
            progress_callback("Đang kiểm tra lại ô")
            return {
                "operation": "posting",
                "has_changes": True,
                "conflicts": [],
            }

        def apply(
            self, plan: Any, resolutions: Any, *, progress_callback
        ) -> Any:
            self.apply_calls.append((plan, resolutions))
            return {"message": "Hoàn tất", "operation": "posting"}

    service = RefiningService()
    controller = ExcelTaskController(expense_posting_service=service)
    ready: list[Any] = []
    completed: list[Any] = []
    controller.analysis_ready.connect(ready.append)
    controller.completed.connect(completed.append)

    try:
        controller.start_posting()
        qtbot.waitUntil(lambda: bool(ready), timeout=2000)
        controller.refine_plan(
            ready[0],
            {
                "row": {
                    "conflict_id": "row",
                    "action": "SELECT_ROW",
                    "selected_row": 12,
                }
            },
        )
        qtbot.waitUntil(lambda: bool(completed), timeout=2000)

        assert service.refine_calls
        assert service.apply_calls
        assert service.apply_calls[0][1] == {}
    finally:
        controller.shutdown()


def test_excel_controller_notifies_service_when_user_cancels(qtbot) -> None:
    plan = {
        "operation": "posting",
        "conflicts": [{"conflict_id": "c1", "type": "CONTAINER_NOT_FOUND"}],
    }

    class CancellableService(_Service):
        def __init__(self) -> None:
            super().__init__(plan)
            self.cancelled: list[Any] = []

        def cancel(self, value: Any) -> None:
            self.cancelled.append(value)

    service = CancellableService()
    controller = ExcelTaskController(expense_posting_service=service)
    ready: list[Any] = []
    controller.analysis_ready.connect(ready.append)

    try:
        controller.start_posting()
        qtbot.waitUntil(lambda: bool(ready), timeout=2000)

        assert controller.cancel_waiting()
        assert service.cancelled == [plan]
        assert not controller.is_busy
    finally:
        controller.shutdown()


def test_month_and_conflict_dialogs_collect_generic_mapping(qtbot) -> None:
    months = MonthSelectionDialog(
        [
            {"sheet_name": "T06 26", "month": 6, "year": 2026, "match_count": 2},
            {
                "sheet_name": "T07 26",
                "month": 7,
                "year": 2026,
                "match_count": 4,
                "is_recent": True,
            },
        ]
    )
    qtbot.addWidget(months)
    months.table.selectRow(1)

    assert months.selected_sheet_name == "T07 26"
    assert months.selection()["selected_sheet_name"] == "T07 26"

    conflicts = ConflictResolutionDialog(
        [
            {
                "conflict_id": "occupied",
                "type": "TARGET_CELL_OCCUPIED",
                "container": "DRYU3026167",
                "fee": "VTN",
                "amount": 1_000_000,
                "target_cell": "Q12",
                "current_value": 800_000,
            },
            {
                "conflict_id": "unknown",
                "type": "UNKNOWN_FEE_CODE",
                "fee": "CXD",
                "amount": 500_000,
            },
        ]
    )
    qtbot.addWidget(conflicts)
    occupied_combo = conflicts._action_combos["occupied"]
    occupied_combo.setCurrentIndex(occupied_combo.findData("ADD"))
    fee_action = conflicts._action_combos["unknown"]
    fee_action.setCurrentIndex(fee_action.findData("SELECT_FEE"))
    conflicts._selected_fees["unknown"].setCurrentIndex(
        conflicts._selected_fees["unknown"].findData("SC")
    )

    result = conflicts.resolution_map()

    assert result["occupied"]["action"] == "ADD"
    assert result["unknown"]["action"] == "SELECT_FEE"
    assert result["unknown"]["selected_fee"] == "SC"


def test_manual_row_picker_returns_only_workbook_row(qtbot) -> None:
    dialog = ManualRowPickerDialog(
        [
            {
                "row_number": 12,
                "sqt": 700,
                "container": "DRYU3026167",
                "goods_type": "Gạo",
                "closing_date": "28/07/2026",
                "vessel": "Tàu A",
                "recipient": "Công ty B",
            }
        ],
        sheet_name="T07 26",
    )
    qtbot.addWidget(dialog)
    dialog.table.selectRow(0)

    assert dialog.selected_row == 12
    assert dialog.table.columnCount() == 6
    assert "Cột" not in [
        dialog.table.horizontalHeaderItem(column).text()
        for column in range(dialog.table.columnCount())
    ]

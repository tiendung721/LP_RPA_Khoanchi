from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QAbstractButton, QLabel, QLineEdit

from app.application import ApplicationRuntime, configured_data_root
from app.config import AppPaths, AppSettings, ConfigManager
from app.constants import APP_STATE_LAST_OUTPUT_SCAN
from app.ui.main_window import MainWindow


def _isolated_runtime(tmp_path: Path) -> ApplicationRuntime:
    data_root = tmp_path / "runtime"
    output_dir = tmp_path / "Output"
    paths = AppPaths.from_data_root(data_root, output_dir)
    ConfigManager(paths=paths).save(
        AppSettings(data_root=data_root, output_dir=output_dir)
    )
    return ApplicationRuntime(data_root)


def test_runtime_and_main_window_start_with_isolated_data_root(
    qtbot, tmp_path: Path
) -> None:
    runtime = _isolated_runtime(tmp_path)
    window = MainWindow(controller=runtime, start_watcher=False)
    qtbot.addWidget(window)

    try:
        window.show()
        qtbot.wait(20)

        assert window.isVisible()
        assert runtime.paths.settings_path.is_file()
        assert runtime.paths.database_path.is_file()
        assert runtime.paths.logs_dir.is_dir()
        assert runtime.paths.excel_temp_dir.is_dir()
        assert runtime.paths.excel_backup_dir.is_dir()
        assert runtime.paths.excel_reports_dir.is_dir()
        assert runtime.paths.rpa_dir.is_dir()
        assert runtime.daily_sync_service is not None
        assert runtime.expense_posting_service is not None
        assert runtime.payment_sync_service is not None
        assert runtime.excel_task_controller is not None
        assert runtime.rpa_expense_controller is not None
        assert window.pages.count() == 4
        assert window.workflow_page.open_assistant_button.text() == "Mở Trợ lý ảo"
        assert not hasattr(window.workflow_page, "open_inbox_button")
        assert not hasattr(window.workflow_page, "choose_file_button")
        assert (
            window.workflow_page.sync_daily_button.text()
            == "Đồng bộ dữ liệu Hàng ngày"
        )
        assert (
            window.workflow_page.post_expenses_button.text()
            == "Nhập khoản chi vào BK"
        )
        assert (
            window.workflow_page.sync_payment_button.text()
            == "Đồng bộ BK → Thanh toán"
        )
        settings_edits = window.settings_page.findChildren(QLineEdit)
        assert {
            "assistantBatEdit",
            "outputDirEdit",
            "containerGptBatEdit",
            "rpaExpenseBatEdit",
        }.issubset({edit.objectName() for edit in settings_edits})
        assert {
            edit.objectName()
            for edit in settings_edits
            if not edit.objectName().startswith("qt_")
        } == {
            "assistantBatEdit",
            "outputDirEdit",
            "dailyWorkbookEdit",
            "bkWorkbookEdit",
            "paymentWorkbookEdit",
            "containerGptBatEdit",
            "rpaExpenseBatEdit",
        }
        visible_text = " ".join(
            widget.text()
            for widget_type in (QLabel, QAbstractButton)
            for widget in window.findChildren(widget_type)
        ).casefold()
        assert "inbox" not in visible_text
        assert "outlook" not in visible_text
        assert "power automate" not in visible_text
        assert "webview2" not in visible_text
        runtime.record_output_scan(0)
        assert runtime.repository.get_app_state(APP_STATE_LAST_OUTPUT_SCAN)
    finally:
        window.close()
        runtime.close()


def test_configured_data_root_prefers_cli_then_environment(tmp_path: Path) -> None:
    cli = tmp_path / "cli"
    env = tmp_path / "env"

    assert configured_data_root(cli, environment={"TRO_LY_DATA_ROOT": str(env)}) == cli
    assert configured_data_root(None, environment={"TRO_LY_DATA_ROOT": str(env)}) == env
    assert configured_data_root(None, environment={}) is None


def test_expense_watcher_ignores_container_json_with_any_filename(
    tmp_path: Path,
) -> None:
    runtime = _isolated_runtime(tmp_path)
    result = runtime.paths.output_dir / "ket_qua_boc_tach_result.json"
    result.write_text(
        json.dumps({"containers": ["VSGU2250713"]}),
        encoding="utf-8",
    )

    try:
        assert runtime._receive_watcher_file(result) is None
        assert runtime.repository.list_batches() == []
    finally:
        runtime.close()


def test_new_download_automatically_opens_review_window(
    qtbot, tmp_path: Path
) -> None:
    runtime = _isolated_runtime(tmp_path)
    window = MainWindow(controller=runtime, start_watcher=False)
    qtbot.addWidget(window)
    source = runtime.paths.output_dir / "ket_qua_boc_tach.json"
    source.write_text(
        json.dumps(
            {
                "v": 1,
                "d": [["DRYU3026167", None, "VTN", "CV", None, None, 100]],
            }
        ),
        encoding="utf-8",
    )

    try:
        result = runtime.batch_service.receive_file(source)
        window._apply_receive_result(result, automatic=True)
        qtbot.wait(20)

        assert result.batch.id in window._review_windows
        old_review = window._review_windows[result.batch.id]
        assert old_review.isVisible()
        old_review.model.mark_dirty()

        incoming = runtime.paths.output_dir / "ket_qua_boc_tach (1).json"
        incoming.write_text(
            json.dumps(
                {
                    "v": 1,
                    "d": [["GAOU2112422", None, "VTN", "CV", None, None, 200]],
                }
            ),
            encoding="utf-8",
        )
        replacement = runtime.batch_service.receive_file(incoming)
        window._apply_receive_result(replacement, automatic=True)
        qtbot.wait(20)

        assert replacement.batch.id != result.batch.id
        assert result.batch.id not in window._review_windows
        assert replacement.batch.id in window._review_windows
        assert window._review_windows[replacement.batch.id].isVisible()
        assert (
            window._review_windows[replacement.batch.id].model.rows()[0].amount
            == 200
        )
    finally:
        window.close()
        runtime.close()

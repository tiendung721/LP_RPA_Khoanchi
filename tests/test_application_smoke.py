from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QAbstractButton, QLabel, QLineEdit

from app.application import ApplicationRuntime, configured_data_root
from app.constants import APP_STATE_LAST_OUTPUT_SCAN
from app.ui.main_window import MainWindow


def test_runtime_and_main_window_start_with_isolated_data_root(
    qtbot, tmp_path: Path
) -> None:
    runtime = ApplicationRuntime(tmp_path / "runtime")
    window = MainWindow(controller=runtime, start_watcher=False)
    qtbot.addWidget(window)

    try:
        window.show()
        qtbot.wait(20)

        assert window.isVisible()
        assert runtime.paths.settings_path.is_file()
        assert runtime.paths.database_path.is_file()
        assert runtime.paths.logs_dir.is_dir()
        assert window.pages.count() == 4
        assert window.workflow_page.open_assistant_button.text() == "Mở Trợ lý ảo"
        assert not hasattr(window.workflow_page, "open_inbox_button")
        assert not hasattr(window.workflow_page, "choose_file_button")
        assert len(window.settings_page.findChildren(QLineEdit)) == 2
        visible_text = " ".join(
            widget.text()
            for widget_type in (QLabel, QAbstractButton)
            for widget in window.findChildren(widget_type)
        ).casefold()
        assert "inbox" not in visible_text
        assert "gpt" not in visible_text
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

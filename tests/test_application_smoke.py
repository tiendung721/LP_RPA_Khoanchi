from __future__ import annotations

from pathlib import Path

from app.application import ApplicationRuntime, configured_data_root
from app.constants import APP_STATE_LAST_INBOX_SCAN
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
        assert window.workflow_page.open_gpt_button.text() == "Mở trợ lý GPT"
        runtime.record_inbox_scan(0)
        assert runtime.repository.get_app_state(APP_STATE_LAST_INBOX_SCAN)
    finally:
        window.close()
        runtime.close()


def test_configured_data_root_prefers_cli_then_environment(tmp_path: Path) -> None:
    cli = tmp_path / "cli"
    env = tmp_path / "env"

    assert configured_data_root(cli, environment={"TRO_LY_DATA_ROOT": str(env)}) == cli
    assert configured_data_root(None, environment={"TRO_LY_DATA_ROOT": str(env)}) == env
    assert configured_data_root(None, environment={}) is None

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox

from app.config import AppSettings
from app.container_load.contracts import ContainerLoadResult, ContainerLoadSession
from app.container_load.validation import load_container_result, row_fingerprint
from app.ui.container_load_controller import (
    ContainerLoadBusyError,
    ContainerLoadController,
)
from app.ui.container_load_dialog import ContainerLoadPreviewDialog
from app.ui.review_table_model import ReviewTableModel
from app.ui.review_window import ReviewWindow


def _payload(amount: object = 100) -> dict:
    return {
        "metadata": {"id": 9, "status": "REVIEWING"},
        "document": {
            "v": 1,
            "d": [
                [None, "VS26060269", "CB", "HD", "HD-130", "Vận tải ABC", amount],
                ["DRYU3026167", None, "VTN", "CV", None, None, 50],
                [None, None, "VTN", "CV", None, None, 25],
            ],
        },
    }


class _FakeWatcher(QObject):
    file_ready = Signal(str)
    file_rejected = Signal(str, str)
    watcher_error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.is_running = False
        self.restart_calls: list[tuple[Path, str]] = []

    def restart(self, output_dir, *, file_pattern):
        self.restart_calls.append((Path(output_dir), file_pattern))
        self.is_running = True
        return True

    def stop(self):
        was_running = self.is_running
        self.is_running = False
        return was_running


class _Service:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.clear_calls = 0
        self.launch_calls = 0

    def update_settings(self, settings) -> None:
        self.output_dir = Path(settings.output_dir)

    def clear_old_results(self) -> int:
        self.clear_calls += 1
        return 0

    def snapshot_json_files(self) -> dict[str, tuple[int, int]]:
        snapshot = {}
        for candidate in self.output_dir.glob("*.json"):
            signature = self.file_signature(candidate)
            if signature is not None:
                snapshot[self.path_key(candidate)] = signature
        return snapshot

    def launch_custom_gpt(self) -> object:
        self.launch_calls += 1
        return object()

    def keep_only(self, newest) -> int:
        return 0

    @staticmethod
    def file_signature(path):
        candidate = Path(path)
        if not candidate.is_file():
            return None
        stat_result = candidate.stat()
        return stat_result.st_size, stat_result.st_mtime_ns

    @staticmethod
    def path_key(path):
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    @staticmethod
    def load_result(path):
        return load_container_result(path)


class _ReviewController(QObject):
    started = Signal(object)
    progress = Signal(str, str, str)
    resultReady = Signal(object, object)
    resultRejected = Signal(object, str, str)
    failed = Signal(object, str)

    def __init__(self) -> None:
        super().__init__()
        self.active: ContainerLoadSession | None = None
        self.finished: list[str] = []

    def start_load(self, **kwargs):
        if self.active is not None:
            raise ContainerLoadBusyError("Đang bận.")
        snapshot = kwargs["row_snapshot"]
        self.active = ContainerLoadSession(
            session_id="session-1",
            batch_id=kwargs["batch_id"],
            source_row=kwargs["source_row"],
            row_runtime_id=kwargs["row_runtime_id"],
            row_fingerprint=row_fingerprint(snapshot),
            requested_bl=str(snapshot[1]),
            started_at_ns=0,
        )
        self.started.emit(self.active)
        return self.active

    def finish(self, session_id: str) -> bool:
        if self.active is None or self.active.session_id != session_id:
            return False
        self.finished.append(session_id)
        self.active = None
        return True

    def cancel_for_batch(self, batch_id):
        if self.active is None or self.active.batch_id != batch_id:
            return False
        return self.finish(self.active.session_id)


def test_inline_action_only_exists_for_missing_container_with_bl(qtbot) -> None:
    window = ReviewWindow(_payload())
    qtbot.addWidget(window)
    model = window.model

    try:
        action = model.index(0, ReviewTableModel.COLUMN_LOOKUP_ACTION)
        assert action.data(ReviewTableModel.ACTION_VISIBLE_ROLE)
        assert action.data(ReviewTableModel.ACTION_ENABLED_ROLE)
        assert action.data() == "Load số cont"
        assert not model.index(
            1, ReviewTableModel.COLUMN_LOOKUP_ACTION
        ).data(ReviewTableModel.ACTION_VISIBLE_ROLE)
        assert not model.index(
            2, ReviewTableModel.COLUMN_LOOKUP_ACTION
        ).data(ReviewTableModel.ACTION_VISIBLE_ROLE)

        model.set_lookup_busy(True)
        assert action.data(ReviewTableModel.ACTION_ENABLED_ROLE)

        runtime_id = model.runtime_id_at(0)
        model.set_lookup_presentation(
            runtime_id,
            status="WAITING_RESULT",
            message="Đang chờ.",
            session_id="session-1",
        )
        assert action.data() == "Hủy Load"
        assert action.data(ReviewTableModel.ACTION_ENABLED_ROLE)
    finally:
        window.model.mark_clean()
        window.close()


def test_controller_allows_only_one_active_load_and_reports_busy(
    qtbot,
    tmp_path: Path,
) -> None:
    output = tmp_path / "Output"
    output.mkdir()
    settings = AppSettings(data_root=tmp_path, output_dir=output)
    service = _Service(output)
    watcher = _FakeWatcher()
    controller = ContainerLoadController(
        service,  # type: ignore[arg-type]
        settings,
        watcher=watcher,  # type: ignore[arg-type]
    )
    session = controller.start_load(
        batch_id=9,
        source_row=0,
        row_runtime_id="row-1",
        row_snapshot=[None, "VS26060269", "CB", "HD", "HD-130", "Vận tải ABC", 100],
    )

    try:
        assert controller.is_busy
        assert service.clear_calls == 1
        assert service.launch_calls == 1
        assert watcher.restart_calls == [(output, "*.json")]
        with pytest.raises(ContainerLoadBusyError, match="Đang chờ"):
            controller.start_load(
                batch_id=9,
                source_row=1,
                row_runtime_id="row-2",
                row_snapshot=[None, "BL2", "CB", "HD", None, None, 100],
            )
        assert service.clear_calls == 1
        assert service.launch_calls == 1
    finally:
        controller.finish(session.session_id)
        controller.shutdown()


def test_controller_accepts_valid_json_and_keeps_session_until_confirmation(
    qtbot,
    tmp_path: Path,
) -> None:
    output = tmp_path / "Output"
    output.mkdir()
    settings = AppSettings(data_root=tmp_path, output_dir=output)
    service = _Service(output)
    watcher = _FakeWatcher()
    controller = ContainerLoadController(
        service,  # type: ignore[arg-type]
        settings,
        watcher=watcher,  # type: ignore[arg-type]
    )
    received: list[tuple[ContainerLoadSession, ContainerLoadResult]] = []
    controller.resultReady.connect(lambda session, result: received.append((session, result)))
    session = controller.start_load(
        batch_id=9,
        source_row=0,
        row_runtime_id="row-1",
        row_snapshot=[None, "VS26060269", "CB", "HD", "HD-130", "Vận tải ABC", 100],
    )
    result_file = output / "tên tải về bất kỳ.json"
    result_file.write_text(
        json.dumps({"containers": ["MSCU1234566", "DRYU3026167"]}),
        encoding="utf-8",
    )

    try:
        watcher.file_ready.emit(str(result_file))
        assert len(received) == 1
        assert received[0][1].containers == ("MSCU1234566", "DRYU3026167")
        assert controller.is_busy
        assert not watcher.is_running
    finally:
        controller.finish(session.session_id)
        controller.shutdown()


def test_controller_ignores_existing_and_non_container_json(
    qtbot,
    tmp_path: Path,
) -> None:
    output = tmp_path / "Output"
    output.mkdir()
    existing = output / "existing-data.json"
    existing.write_text('{"v":1,"d":[]}', encoding="utf-8")
    settings = AppSettings(data_root=tmp_path, output_dir=output)
    service = _Service(output)
    watcher = _FakeWatcher()
    controller = ContainerLoadController(
        service,  # type: ignore[arg-type]
        settings,
        watcher=watcher,  # type: ignore[arg-type]
    )
    ready: list[object] = []
    rejected: list[object] = []
    controller.resultReady.connect(lambda *args: ready.append(args))
    controller.resultRejected.connect(lambda *args: rejected.append(args))
    session = controller.start_load(
        batch_id=9,
        source_row=0,
        row_runtime_id="row-1",
        row_snapshot=[None, "VS26060269", "CB", "HD", "HD-130", "Vận tải ABC", 100],
    )

    try:
        watcher.file_ready.emit(str(existing))
        assert ready == []
        assert rejected == []

        unrelated_new = output / "new-main-result.json"
        unrelated_new.write_text('{"v":1,"d":[]}', encoding="utf-8")
        watcher.file_ready.emit(str(unrelated_new))
        assert ready == []
        assert rejected == []
        assert controller.is_busy

        existing.write_text(
            json.dumps({"containers": ["VSGU2250713"]}),
            encoding="utf-8",
        )
        watcher.file_ready.emit(str(existing))
        assert len(ready) == 1
        assert controller.is_busy
    finally:
        controller.finish(session.session_id)
        controller.shutdown()


def test_review_confirmation_replaces_row_and_splits_amount_exactly(
    qtbot,
    monkeypatch,
    tmp_path: Path,
) -> None:
    controller = _ReviewController()
    window = ReviewWindow(_payload(), container_load_controller=controller)
    qtbot.addWidget(window)
    monkeypatch.setattr(
        ContainerLoadPreviewDialog,
        "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )

    try:
        assert window.start_container_load(0)
        assert controller.active is not None
        controller.resultReady.emit(
            controller.active,
            ContainerLoadResult(
                tmp_path / "so_cont_shipping.json",
                ("MSCU1234566", "DRYU3026167", "GAOU2112422"),
            ),
        )

        assert window.model.rows_as_arrays()[:3] == [
            ["MSCU1234566", "VS26060269", "CB", "HD", "HD-130", "Vận tải ABC", 34],
            ["DRYU3026167", "VS26060269", "CB", "HD", "HD-130", "Vận tải ABC", 33],
            ["GAOU2112422", "VS26060269", "CB", "HD", "HD-130", "Vận tải ABC", 33],
        ]
        assert window.model.dirty
        assert controller.finished == ["session-1"]
    finally:
        window.model.mark_clean()
        window.close()


def test_invalid_amount_disables_confirmation(qtbot, tmp_path: Path) -> None:
    from app.container_load.validation import allocate_amount

    dialog = ContainerLoadPreviewDialog(
        bl="VS26060269",
        source_path=tmp_path / "so_cont_shipping.json",
        original_amount="100",
        allocations=allocate_amount(
            "100",
            ("MSCU1234566", "DRYU3026167"),
        ),
    )
    qtbot.addWidget(dialog)

    confirm = dialog.findChild(QDialogButtonBox).button(
        QDialogButtonBox.StandardButton.Ok
    )
    assert not dialog.can_confirm
    assert not confirm.isEnabled()


def test_second_click_only_shows_busy_message(qtbot, monkeypatch) -> None:
    controller = _ReviewController()
    window = ReviewWindow(_payload(), container_load_controller=controller)
    qtbot.addWidget(window)
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda parent, title, text: messages.append((title, text)),
    )

    try:
        assert window.start_container_load(0)
        assert not window.start_container_load(0)
        assert messages == [("Load số container đang bận", "Đang bận.")]
        assert controller.active is not None
    finally:
        window.close()


def test_cancel_button_stops_active_load_and_restores_load_action(
    qtbot,
    monkeypatch,
) -> None:
    controller = _ReviewController()
    window = ReviewWindow(_payload(), container_load_controller=controller)
    qtbot.addWidget(window)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    try:
        assert window.start_container_load(0)
        action = window.model.index(
            0, ReviewTableModel.COLUMN_LOOKUP_ACTION
        )
        assert action.data() == "Hủy Load"

        assert window.cancel_container_load(0)

        runtime_id = window.model.runtime_id_at(0)
        presentation = window.model.lookup_presentation(runtime_id)
        assert controller.active is None
        assert controller.finished == ["session-1"]
        assert presentation.status == "CANCELLED"
        assert presentation.session_id is None
        assert action.data() == "Load số cont"
        assert not window.model.dirty
    finally:
        window.close()

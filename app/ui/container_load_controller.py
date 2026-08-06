"""Qt controller quản lý duy nhất một lượt chờ JSON số container."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QObject, Signal, Slot

from app.config import AppSettings
from app.container_load.contracts import ContainerLoadSession
from app.container_load.service import CONTAINER_RESULT_PATTERN, ContainerLoadService
from app.container_load.validation import (
    ContainerResultValidationError,
    row_fingerprint,
)
from app.services.output_watcher import OutputWatcher

LOGGER = logging.getLogger(__name__)


class ContainerLoadBusyError(RuntimeError):
    pass


class ContainerLoadController(QObject):
    started = Signal(object)
    progress = Signal(str, str, str)
    resultReady = Signal(object, object)
    resultRejected = Signal(object, str, str)
    failed = Signal(object, str)
    finished = Signal(str)
    busyChanged = Signal(bool)

    def __init__(
        self,
        service: ContainerLoadService,
        settings: AppSettings,
        parent: QObject | None = None,
        *,
        watcher: OutputWatcher | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.settings = settings
        self._lock = RLock()
        self._active_session: ContainerLoadSession | None = None
        self._baseline_signatures: dict[str, tuple[int, int]] = {}
        self._closed = False
        self._watcher = watcher or OutputWatcher(
            settings.output_dir,
            file_pattern=CONTAINER_RESULT_PATTERN,
            parent=self,
        )
        self._watcher.file_ready.connect(self._result_file_ready)
        self._watcher.file_rejected.connect(self._result_file_rejected)
        self._watcher.watcher_error.connect(self._watcher_failed)

    @property
    def active_session(self) -> ContainerLoadSession | None:
        with self._lock:
            return self._active_session

    @property
    def is_busy(self) -> bool:
        return self.active_session is not None

    def update_settings(self, settings: AppSettings) -> None:
        if self.is_busy:
            raise RuntimeError(
                "Không thể đổi cấu hình khi đang chờ kết quả số container."
            )
        self.settings = settings
        self.service.update_settings(settings)

    def start_load(
        self,
        *,
        batch_id: int | None,
        source_row: int,
        row_runtime_id: str,
        row_snapshot: list[Any] | tuple[Any, ...],
    ) -> ContainerLoadSession:
        with self._lock:
            if self._closed:
                raise RuntimeError("Bộ Load số container đã đóng.")
            active = self._active_session
            if active is not None:
                raise ContainerLoadBusyError(
                    "Đang chờ kết quả Load số cont cho "
                    f"B/L {active.requested_bl}."
                )
        if len(row_snapshot) != 7:
            raise ValueError("Dòng Load số cont phải có đúng 7 giá trị.")
        container, bl = row_snapshot[0], row_snapshot[1]
        if isinstance(container, str) and container.strip():
            raise ValueError("Dòng đã có số container.")
        if not isinstance(bl, str) or not bl.strip():
            raise ValueError("Dòng chưa có B/L để Load số container.")

        session = ContainerLoadSession(
            session_id=uuid4().hex,
            batch_id=batch_id,
            source_row=source_row,
            row_runtime_id=row_runtime_id,
            row_fingerprint=row_fingerprint(row_snapshot),
            requested_bl=bl.strip(),
            started_at_ns=time.time_ns(),
        )
        with self._lock:
            if self._active_session is not None:
                raise ContainerLoadBusyError(
                    "Một lượt Load số container khác vừa bắt đầu."
                )
            self._active_session = session
        self.busyChanged.emit(True)
        try:
            self.service.clear_old_results()
            self._baseline_signatures = self.service.snapshot_json_files()
            if not self._watcher.restart(
                self.settings.output_dir,
                file_pattern=CONTAINER_RESULT_PATTERN,
            ):
                raise RuntimeError(
                    "Không thể theo dõi file JSON trong Output."
                )
            self.service.launch_custom_gpt()
        except Exception:
            self._release(session.session_id)
            raise
        self.started.emit(session)
        self.progress.emit(
            session.session_id,
            "WAITING_RESULT",
            f"Đang chờ file JSON kết quả cho B/L {session.requested_bl}.",
        )
        return session

    def finish(self, session_id: str) -> bool:
        return self._release(session_id)

    def cancel(self, session_id: str) -> bool:
        """Dừng lượt chờ hiện tại nhưng không đóng cửa sổ Custom GPT."""

        return self._release(session_id)

    def cancel_for_batch(self, batch_id: int | None) -> bool:
        session = self.active_session
        if session is None or session.batch_id != batch_id:
            return False
        return self.cancel(session.session_id)

    @Slot(str)
    def _result_file_ready(self, raw_path: str) -> None:
        session = self.active_session
        if session is None:
            return
        path = Path(raw_path)
        signature = self.service.file_signature(path)
        if signature is None:
            return
        baseline_signature = self._baseline_signatures.get(
            self.service.path_key(path)
        )
        if baseline_signature == signature:
            LOGGER.debug("Bỏ qua file JSON đã tồn tại trước lượt Load: %s", path)
            return
        try:
            result = self.service.load_result(path)
        except ContainerResultValidationError as exc:
            message = str(exc)
            if exc.code in {"INVALID_JSON", "INVALID_SCHEMA"}:
                waiting_message = (
                    f"Đã bỏ qua {path.name} vì không phải JSON số container; "
                    "vẫn đang chờ kết quả."
                )
                LOGGER.info("%s Chi tiết: %s", waiting_message, message)
                self.progress.emit(
                    session.session_id,
                    "WAITING_RESULT",
                    waiting_message,
                )
                return
            self.progress.emit(session.session_id, "INVALID_RESULT", message)
            self.resultRejected.emit(session, raw_path, message)
            return
        except Exception as exc:
            LOGGER.exception("Không xử lý được kết quả số container: %s", path)
            message = str(exc) or "Không xử lý được file kết quả số container."
            self.progress.emit(session.session_id, "FAILED", message)
            self.resultRejected.emit(session, raw_path, message)
            return
        self.service.keep_only(path)
        self._watcher.stop()
        self.progress.emit(
            session.session_id,
            "RESULT_READY",
            f"Đã nhận {len(result.containers)} số container.",
        )
        self.resultReady.emit(session, result)

    @Slot(str, str)
    def _result_file_rejected(self, raw_path: str, message: str) -> None:
        session = self.active_session
        if session is None:
            return
        self.progress.emit(session.session_id, "INVALID_RESULT", message)
        self.resultRejected.emit(session, raw_path, message)

    @Slot(str)
    def _watcher_failed(self, message: str) -> None:
        session = self.active_session
        if session is None:
            return
        self.failed.emit(session, message)
        self._release(session.session_id)

    def _release(self, session_id: str) -> bool:
        with self._lock:
            session = self._active_session
            if session is None or session.session_id != session_id:
                return False
            self._active_session = None
            self._baseline_signatures = {}
        try:
            self._watcher.stop()
        finally:
            self.busyChanged.emit(False)
            self.finished.emit(session_id)
        return True

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            session = self._active_session
        if session is not None:
            self._release(session.session_id)
        else:
            self._watcher.stop()

    close = shutdown


__all__ = ["ContainerLoadBusyError", "ContainerLoadController"]

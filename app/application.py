"""Khởi tạo và quản lý vòng đời các service của ứng dụng."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import Any

from app.config import AppPaths, AppSettings, ConfigManager
from app.constants import (
    APP_STATE_LAST_INBOX_SCAN,
    APP_STATE_LAST_PAGE,
    APP_STATE_MAIN_WINDOW_GEOMETRY,
)
from app.database import Database
from app.logging_setup import setup_logging
from app.repositories.batch_repository import BatchRepository
from app.repositories.batch_repository import local_now_iso
from app.services.batch_service import BatchService
from app.services.browser_launcher import BrowserLauncher
from app.services.inbox_watcher import InboxWatcher
from app.services.json_codec import JsonCodec
from app.services.reviewed_batch_provider import ReviewedBatchProvider
from app.services.validation_service import ValidationService

LOGGER = logging.getLogger(__name__)


class ApplicationRuntime:
    """Composition root duy nhất cho UI, service và tài nguyên runtime."""

    def __init__(self, data_root: str | Path | None = None) -> None:
        bootstrap_paths = (
            AppPaths.from_data_root(Path(data_root).expanduser())
            if data_root is not None
            else AppPaths.defaults()
        )
        bootstrap_paths.ensure_directories()
        setup_logging(bootstrap_paths)

        self.config_manager = ConfigManager(paths=bootstrap_paths)
        self.settings = self.config_manager.load()
        self.paths = self.settings.paths
        self.paths.ensure_directories()
        self.log_path = setup_logging(self.paths)

        self.database = Database(self.paths.database_path)
        self.repository = BatchRepository(self.database)
        self.validation_service = ValidationService()
        self.validator = self.validation_service
        self.json_codec = JsonCodec()
        self.batch_service = BatchService(
            self.paths,
            self.repository,
            codec=self.json_codec,
            validation_service=self.validation_service,
            max_file_size_bytes=self.settings.max_file_size_bytes,
        )
        self.reviewed_batch_provider = ReviewedBatchProvider(self.batch_service)
        self.browser_launcher = BrowserLauncher(self.settings)
        self.watcher = InboxWatcher(
            self.settings,
            on_file_ready=self._receive_watcher_file,
        )
        self.inbox_watcher = self.watcher
        self._close_lock = RLock()
        self._closed = False
        LOGGER.info(
            "Khởi tạo runtime thành công; data_root=%s, inbox=%s",
            self.paths.data_root,
            self.settings.inbox_dir,
        )

    def _receive_watcher_file(self, path: Path) -> object:
        """Nhận callback đã được watcher chuyển an toàn về Qt owner thread."""

        LOGGER.info("Watcher chuyển file ổn định sang BatchService: %s", path.name)
        return self.batch_service.receive_file(path)

    def apply_settings(self, settings: AppSettings) -> AppSettings:
        """Lưu cấu hình và cập nhật các service không cần tái tạo database."""

        if not isinstance(settings, AppSettings):
            raise TypeError("Cấu hình mới phải là AppSettings.")
        old_root = self.paths.data_root.resolve()
        new_paths = settings.paths
        if new_paths.data_root.resolve() != old_root:
            raise ValueError(
                "Không thể đổi data_root khi ứng dụng đang chạy. "
                "Hãy đóng ứng dụng và khởi động lại với --data-root."
            )
        new_paths.ensure_directories()
        self.config_manager.save(settings)
        self.settings = settings
        self.paths = new_paths
        self.batch_service.max_file_size_bytes = settings.max_file_size_bytes
        self.browser_launcher.update_settings(settings)
        LOGGER.info(
            "Đã áp dụng cấu hình; inbox=%s, pattern=%s, stable=%ss, max=%sMB",
            settings.inbox_dir,
            settings.file_pattern,
            settings.stable_seconds,
            settings.max_file_size_mb,
        )
        return settings

    update_settings = apply_settings
    save_settings = apply_settings

    def save_ui_state(self, state: Mapping[str, Any]) -> None:
        geometry = state.get("geometry")
        page = state.get("page", state.get("page_index"))
        self.repository.set_app_state(
            APP_STATE_MAIN_WINDOW_GEOMETRY,
            str(geometry) if geometry else None,
        )
        self.repository.set_app_state(
            APP_STATE_LAST_PAGE,
            str(page) if isinstance(page, int) else None,
        )

    def restore_ui_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {}
        geometry = self.repository.get_app_state(APP_STATE_MAIN_WINDOW_GEOMETRY)
        page = self.repository.get_app_state(APP_STATE_LAST_PAGE)
        if geometry:
            state["geometry"] = geometry
        if page is not None:
            try:
                state["page"] = int(page)
            except ValueError:
                self.repository.set_app_state(APP_STATE_LAST_PAGE, None)
        return state

    load_ui_state = restore_ui_state

    def record_inbox_scan(self, _candidate_count: int = 0) -> None:
        """Lưu thời điểm quét Inbox gần nhất để chẩn đoán/khôi phục trạng thái."""

        self.repository.set_app_state(APP_STATE_LAST_INBOX_SCAN, local_now_iso())

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        LOGGER.info("Đang dừng ứng dụng")
        try:
            self.watcher.stop()
        except Exception:
            LOGGER.exception("Không thể dừng watcher sạch")
        try:
            self.database.close()
        except Exception:
            LOGGER.exception("Không thể đóng database sạch")
        logging.shutdown()


def configured_data_root(
    command_line_value: str | Path | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> Path | None:
    """Ưu tiên CLI, sau đó biến môi trường; trả ``None`` để dùng mặc định."""

    if command_line_value:
        return Path(command_line_value).expanduser()
    env = environment if environment is not None else os.environ
    value = env.get("TRO_LY_DATA_ROOT", "").strip()
    return Path(value).expanduser() if value else None

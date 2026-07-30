"""Chuẩn bị Output, mở BAT và đọc kết quả số container."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from app.config import AppSettings
from app.container_load.contracts import ContainerLoadResult
from app.container_load.validation import (
    is_container_result_document,
    load_container_result,
)
from app.services.assistant_bat_launcher import AssistantBatLauncher

LOGGER = logging.getLogger(__name__)

CONTAINER_RESULT_PATTERN = "*.json"
CONTAINER_RESULT_GLOB = "*.json"


class ContainerLoadService:
    def __init__(
        self,
        settings: AppSettings,
        launcher: AssistantBatLauncher,
    ) -> None:
        self.settings = settings
        self.launcher = launcher

    def update_settings(self, settings: AppSettings) -> None:
        self.settings = settings

    @property
    def output_dir(self) -> Path:
        return Path(self.settings.output_dir).expanduser()

    def clear_old_results(self) -> int:
        output = self.output_dir.resolve()
        output.mkdir(parents=True, exist_ok=True)
        removed = 0
        for candidate in output.glob(CONTAINER_RESULT_GLOB):
            if (
                not candidate.is_file()
                or not is_container_result_document(candidate)
            ):
                continue
            candidate.unlink()
            removed += 1
        if removed:
            LOGGER.info("Đã xóa %s file kết quả số container cũ.", removed)
        return removed

    def keep_only(self, newest: str | Path) -> int:
        keep = Path(newest).resolve()
        removed = 0
        for candidate in self.output_dir.resolve().glob(CONTAINER_RESULT_GLOB):
            if (
                not candidate.is_file()
                or candidate.resolve() == keep
                or not is_container_result_document(candidate)
            ):
                continue
            candidate.unlink()
            removed += 1
        return removed

    def snapshot_json_files(self) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        output = self.output_dir.resolve()
        output.mkdir(parents=True, exist_ok=True)
        for candidate in output.glob(CONTAINER_RESULT_GLOB):
            signature = self.file_signature(candidate)
            if signature is not None:
                snapshot[self.path_key(candidate)] = signature
        return snapshot

    @staticmethod
    def file_signature(path: str | Path) -> tuple[int, int] | None:
        candidate = Path(path)
        try:
            if not candidate.is_file():
                return None
            stat_result = candidate.stat()
        except OSError:
            return None
        return stat_result.st_size, stat_result.st_mtime_ns

    @staticmethod
    def path_key(path: str | Path) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    def launch_custom_gpt(self) -> Any:
        bat_path = self.settings.container_gpt_bat_path.strip()
        if not bat_path:
            raise RuntimeError(
                "Chưa cấu hình BAT Load số container trong trang Cài đặt."
            )
        return self.launcher.launch(
            bat_path=bat_path,
            output_dir=self.settings.output_dir,
        )

    @staticmethod
    def load_result(path: str | Path) -> ContainerLoadResult:
        return load_container_result(path)


__all__ = [
    "CONTAINER_RESULT_GLOB",
    "CONTAINER_RESULT_PATTERN",
    "ContainerLoadService",
]

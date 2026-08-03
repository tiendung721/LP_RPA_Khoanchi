"""Khởi chạy BAT của flow PAD nhập khoản chi."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QProcess

from .contracts import (
    PreparedRpaSelection,
    RpaExpenseLaunchResult,
)


class RpaExpenseLaunchError(RuntimeError):
    pass


class RpaExpenseBatLauncher:
    def __init__(self, settings: Any) -> None:
        self.update_settings(settings)

    def update_settings(self, settings: Any) -> None:
        self.settings = settings

    def validate_configuration(
        self, bat_path: str | Path | None = None
    ) -> Path:
        raw = (
            getattr(self.settings, "rpa_expense_bat_path", "")
            if bat_path is None
            else bat_path
        )
        if not str(raw or "").strip():
            raise RpaExpenseLaunchError(
                "Chưa cấu hình BAT nhập lên phần mềm quyết toán."
            )
        path = Path(str(raw)).expanduser()
        if path.suffix.casefold() != ".bat":
            raise RpaExpenseLaunchError("File chạy RPA phải có đuôi .bat.")
        if not path.is_file():
            raise RpaExpenseLaunchError(f"Không tìm thấy file BAT RPA: {path}")
        return path.resolve()

    def launch(
        self,
        prepared: PreparedRpaSelection,
        *,
        bat_path: str | Path | None = None,
    ) -> RpaExpenseLaunchResult:
        bat = self.validate_configuration(bat_path)
        command = os.environ.get("COMSPEC", "cmd.exe")
        started, process_id = QProcess.startDetached(
            command,
            [
                "/d",
                "/s",
                "/c",
                "call",
                str(bat),
                str(prepared.selection_path),
            ],
            str(bat.parent),
        )
        if not started:
            raise RpaExpenseLaunchError(
                "Windows không thể khởi chạy BAT nhập khoản chi."
            )
        return RpaExpenseLaunchResult(
            success=True,
            message=(
                f"Đã khởi chạy PAD cho {prepared.item_count} SQT "
                f"(run {prepared.run_id})."
            ),
            bat_path=bat,
            selection_path=prepared.selection_path,
            run_id=prepared.run_id,
            item_count=prepared.item_count,
            process_id=int(process_id) if process_id else None,
        )


__all__ = [
    "RpaExpenseBatLauncher",
    "RpaExpenseLaunchError",
]

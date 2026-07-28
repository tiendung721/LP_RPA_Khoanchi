"""Mở Trợ lý ảo bằng BAT và cấu hình thư mục tải của profile riêng."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QProcess

LOGGER = logging.getLogger(__name__)


class AssistantLaunchError(RuntimeError):
    """Cấu hình bundle hoặc thao tác khởi chạy không hợp lệ."""


@dataclass(frozen=True, slots=True)
class AssistantLaunchResult:
    success: bool
    message: str
    bat_path: Path
    output_dir: Path
    process_id: int | None = None


@dataclass(frozen=True, slots=True)
class AssistantBundle:
    bat_path: Path
    bundle_root: Path
    powershell_path: Path
    extension_dir: Path
    profile_dir: Path
    preferences_path: Path


class AssistantBatLauncher:
    """Adapter duy nhất giữa ứng dụng và bundle BAT của Trợ lý ảo."""

    def __init__(self, settings: object | Mapping[str, Any] | None = None) -> None:
        self._settings = settings

    def update_settings(self, settings: object | Mapping[str, Any]) -> None:
        self._settings = settings

    def validate_configuration(
        self,
        bat_path: str | Path | None = None,
        output_dir: str | Path | None = None,
    ) -> AssistantBundle:
        raw_bat = (
            self._setting("assistant_bat_path", default="")
            if bat_path is None
            else bat_path
        )
        raw_output = (
            self._setting("output_dir", default="")
            if output_dir is None
            else output_dir
        )
        if not str(raw_bat).strip():
            raise AssistantLaunchError("Chưa cấu hình file BAT mở Trợ lý ảo.")
        if not str(raw_output).strip():
            raise AssistantLaunchError("Chưa cấu hình thư mục Output.")
        bat = Path(raw_bat).expanduser()
        if bat.suffix.casefold() != ".bat":
            raise AssistantLaunchError("File mở Trợ lý ảo phải có đuôi .bat.")
        if not bat.is_file():
            raise AssistantLaunchError(f"Không tìm thấy file BAT: {bat}")

        launcher_dir = bat.resolve().parent
        bundle_root = launcher_dir.parent
        powershell_path = launcher_dir / "open_chatgpt_app.ps1"
        extension_dir = bundle_root / "RPA_ChatGPT_Extension"
        profile_dir = bundle_root / "RPA_ChatGPT_Profile"
        if launcher_dir.name.casefold() != "rpa_chatgpt_launcher":
            raise AssistantLaunchError(
                "BAT không thuộc bundle Trợ lý ảo tương thích."
            )
        if not powershell_path.is_file():
            raise AssistantLaunchError(
                f"Không tìm thấy script của bundle: {powershell_path}"
            )
        if not extension_dir.is_dir():
            raise AssistantLaunchError(
                f"Không tìm thấy extension của bundle: {extension_dir}"
            )
        self._ensure_output_writable(raw_output)
        return AssistantBundle(
            bat_path=bat.resolve(),
            bundle_root=bundle_root,
            powershell_path=powershell_path,
            extension_dir=extension_dir,
            profile_dir=profile_dir,
            preferences_path=profile_dir / "Default" / "Preferences",
        )

    def configure_download_directory(
        self,
        bundle: AssistantBundle,
        output_dir: str | Path,
    ) -> Path:
        output = self._ensure_output_writable(output_dir)

        preferences_path = bundle.preferences_path
        preferences_path.parent.mkdir(parents=True, exist_ok=True)
        preferences: dict[str, Any] = {}
        if preferences_path.exists():
            try:
                loaded = json.loads(preferences_path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise AssistantLaunchError(
                    "Chrome Preferences của Trợ lý ảo bị lỗi; không thể cập nhật "
                    "thư mục tải xuống an toàn."
                ) from exc
            if not isinstance(loaded, dict):
                raise AssistantLaunchError(
                    "Chrome Preferences phải chứa một JSON object."
                )
            preferences = loaded

        download = preferences.get("download")
        if not isinstance(download, dict):
            download = {}
            preferences["download"] = download
        download.update(
            {
                "default_directory": str(output),
                "prompt_for_download": False,
                "directory_upgrade": True,
            }
        )
        self._write_json_atomic(preferences_path, preferences)
        LOGGER.info("Đã cấu hình thư mục tải của Trợ lý ảo: %s", output)
        return preferences_path

    def launch(
        self,
        bat_path: str | Path | None = None,
        output_dir: str | Path | None = None,
    ) -> AssistantLaunchResult:
        raw_output = (
            self._setting("output_dir", default="")
            if output_dir is None
            else output_dir
        )
        bundle = self.validate_configuration(bat_path, raw_output)
        selected_output = Path(raw_output).expanduser()
        self.configure_download_directory(bundle, selected_output)
        command = os.environ.get("COMSPEC", "cmd.exe")
        started, process_id = QProcess.startDetached(
            command,
            ["/d", "/s", "/c", "call", str(bundle.bat_path)],
            str(bundle.bat_path.parent),
        )
        if not started:
            raise AssistantLaunchError(
                "Windows không thể khởi chạy file BAT mở Trợ lý ảo."
            )
        LOGGER.info("Đã chạy BAT Trợ lý ảo: %s (pid=%s)", bundle.bat_path, process_id)
        return AssistantLaunchResult(
            success=True,
            message="Đã mở Trợ lý ảo.",
            bat_path=bundle.bat_path,
            output_dir=selected_output.resolve(),
            process_id=int(process_id) if process_id else None,
        )

    open_assistant = launch

    def _setting(self, name: str, *, default: object) -> object:
        settings = self._settings
        if settings is None:
            return default
        if isinstance(settings, Mapping):
            return settings.get(name, default)
        return getattr(settings, name, default)

    @staticmethod
    def _ensure_output_writable(output_dir: str | Path) -> Path:
        output = Path(output_dir).expanduser().resolve()
        try:
            output.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                prefix=".output-write-test.",
                suffix=".tmp",
                dir=output,
            ):
                pass
        except OSError as exc:
            raise AssistantLaunchError(
                f"Không thể tạo hoặc ghi vào thư mục Output: {output}"
            ) from exc
        return output

    @staticmethod
    def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


__all__ = [
    "AssistantBatLauncher",
    "AssistantBundle",
    "AssistantLaunchError",
    "AssistantLaunchResult",
]

"""Cấu hình và cây thư mục runtime, không phụ thuộc thư mục cài đặt."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from app.constants import (
    APP_SLUG,
    APP_VENDOR,
    DEFAULT_FILE_PATTERN,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_MAX_FILE_SIZE_MB,
    DEFAULT_STABILITY_TIMEOUT_SECONDS,
    DEFAULT_STABLE_SECONDS,
)

_BROWSER_PREFERENCES = frozenset({"auto", "chrome", "edge", "default"})


def default_data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / APP_VENDOR / APP_SLUG


def default_inbox_dir() -> Path:
    user_profile = os.environ.get("USERPROFILE")
    base = Path(user_profile) if user_profile else Path.home()
    return base / "Documents" / APP_SLUG / "Inbox"


@dataclass(frozen=True, slots=True)
class AppPaths:
    data_root: Path
    config_dir: Path
    settings_path: Path
    inbox_dir: Path
    archive_original_dir: Path
    workspace_dir: Path
    ready_dir: Path
    rejected_dir: Path
    database_dir: Path
    database_path: Path
    logs_dir: Path
    log_path: Path
    browser_profile_dir: Path

    @classmethod
    def from_data_root(
        cls,
        data_root: str | Path,
        inbox_dir: str | Path | None = None,
        browser_profile_dir: str | Path | None = None,
    ) -> "AppPaths":
        root = Path(data_root).expanduser()
        inbox = Path(inbox_dir).expanduser() if inbox_dir else root / "Inbox"
        profile = (
            Path(browser_profile_dir).expanduser()
            if browser_profile_dir
            else root / "BrowserProfile"
        )
        config_dir = root / "Config"
        database_dir = root / "Database"
        logs_dir = root / "Logs"
        return cls(
            data_root=root,
            config_dir=config_dir,
            settings_path=config_dir / "settings.json",
            inbox_dir=inbox,
            archive_original_dir=root / "Archive" / "Original",
            workspace_dir=root / "Workspace",
            ready_dir=root / "Ready",
            rejected_dir=root / "Rejected",
            database_dir=database_dir,
            database_path=database_dir / "app_state.db",
            logs_dir=logs_dir,
            log_path=logs_dir / "app.log",
            browser_profile_dir=profile,
        )

    @classmethod
    def defaults(cls) -> "AppPaths":
        return cls.from_data_root(
            default_data_root(),
            inbox_dir=default_inbox_dir(),
        )

    def ensure_directories(self) -> None:
        for directory in self.directories:
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def directories(self) -> tuple[Path, ...]:
        return (
            self.data_root,
            self.config_dir,
            self.inbox_dir,
            self.archive_original_dir,
            self.workspace_dir,
            self.ready_dir,
            self.rejected_dir,
            self.database_dir,
            self.logs_dir,
            self.browser_profile_dir,
        )

    # Các alias giúp code UI đọc tự nhiên hơn.
    @property
    def archive_dir(self) -> Path:
        return self.archive_original_dir

    @property
    def db_path(self) -> Path:
        return self.database_path


@dataclass(slots=True)
class AppSettings:
    data_root: Path = field(default_factory=default_data_root)
    gpt_url: str = ""
    browser_preference: str = "auto"
    browser_executable: str = ""
    browser_profile_dir: Path | None = None
    inbox_dir: Path = field(default_factory=default_inbox_dir)
    file_pattern: str = DEFAULT_FILE_PATTERN
    stable_seconds: float = DEFAULT_STABLE_SECONDS
    stability_timeout_seconds: float = DEFAULT_STABILITY_TIMEOUT_SECONDS
    max_file_size_mb: int = DEFAULT_MAX_FILE_SIZE_MB
    auto_open_review: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.data_root, (str, os.PathLike)):
            raise ValueError("Thư mục dữ liệu phải là một đường dẫn.")
        if not isinstance(self.inbox_dir, (str, os.PathLike)):
            raise ValueError("Thư mục Inbox phải là một đường dẫn.")
        if not str(self.data_root).strip():
            raise ValueError("Thư mục dữ liệu không được để trống.")
        if not str(self.inbox_dir).strip():
            raise ValueError("Thư mục Inbox không được để trống.")
        self.data_root = Path(self.data_root).expanduser()
        self.inbox_dir = Path(self.inbox_dir).expanduser()
        if self.browser_profile_dir is None or not str(
            self.browser_profile_dir
        ).strip():
            self.browser_profile_dir = self.data_root / "BrowserProfile"
        else:
            self.browser_profile_dir = Path(self.browser_profile_dir).expanduser()
        if not isinstance(self.gpt_url, str):
            raise ValueError("URL GPT phải là chuỗi.")
        self.gpt_url = self.gpt_url.strip()
        if isinstance(self.browser_executable, os.PathLike):
            self.browser_executable = os.fspath(self.browser_executable)
        if not isinstance(self.browser_executable, str):
            raise ValueError("Đường dẫn trình duyệt phải là chuỗi.")
        self.browser_executable = self.browser_executable.strip()
        if not isinstance(self.browser_preference, str):
            raise ValueError("Trình duyệt ưu tiên phải là chuỗi.")
        self.browser_preference = self.browser_preference.strip().lower()
        if self.browser_preference == "windows":
            self.browser_preference = "default"
        if self.browser_preference not in _BROWSER_PREFERENCES:
            raise ValueError("Trình duyệt ưu tiên không hợp lệ.")
        if not isinstance(self.file_pattern, str) or not self.file_pattern.strip():
            raise ValueError("Pattern tên file không được để trống.")
        self.file_pattern = self.file_pattern.strip()
        if self.stable_seconds < 0:
            raise ValueError("Số giây ổn định không được âm.")
        if self.stability_timeout_seconds <= 0:
            raise ValueError("Timeout chờ file phải lớn hơn 0.")
        if self.stability_timeout_seconds < self.stable_seconds:
            raise ValueError("Timeout phải lớn hơn hoặc bằng số giây ổn định.")
        if self.max_file_size_mb <= 0:
            raise ValueError("Kích thước file tối đa phải lớn hơn 0.")
        if not isinstance(self.auto_open_review, bool):
            raise ValueError("Tùy chọn tự mở review phải là true hoặc false.")

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def paths(self) -> AppPaths:
        return AppPaths.from_data_root(
            self.data_root,
            inbox_dir=self.inbox_dir,
            browser_profile_dir=self.browser_profile_dir,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_root": str(self.data_root),
            "gpt_url": self.gpt_url,
            "browser_preference": self.browser_preference,
            "browser_executable": self.browser_executable,
            "browser_profile_dir": str(self.browser_profile_dir),
            "inbox_dir": str(self.inbox_dir),
            "file_pattern": self.file_pattern,
            "stable_seconds": self.stable_seconds,
            "stability_timeout_seconds": self.stability_timeout_seconds,
            "max_file_size_mb": self.max_file_size_mb,
            "auto_open_review": self.auto_open_review,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        fallback_paths: AppPaths | None = None,
    ) -> "AppSettings":
        fallback = fallback_paths or AppPaths.defaults()
        known = {
            "data_root": value.get("data_root", fallback.data_root),
            "gpt_url": value.get("gpt_url", ""),
            "browser_preference": value.get("browser_preference", "auto"),
            "browser_executable": value.get("browser_executable", ""),
            "browser_profile_dir": value.get(
                "browser_profile_dir", fallback.browser_profile_dir
            ),
            "inbox_dir": value.get("inbox_dir", fallback.inbox_dir),
            "file_pattern": value.get("file_pattern", DEFAULT_FILE_PATTERN),
            "stable_seconds": value.get(
                "stable_seconds",
                value.get("file_stable_seconds", DEFAULT_STABLE_SECONDS),
            ),
            "stability_timeout_seconds": value.get(
                "stability_timeout_seconds",
                DEFAULT_STABILITY_TIMEOUT_SECONDS,
            ),
            "max_file_size_mb": value.get(
                "max_file_size_mb", DEFAULT_MAX_FILE_SIZE_MB
            ),
            "auto_open_review": value.get("auto_open_review", True),
        }
        try:
            known["stable_seconds"] = float(known["stable_seconds"])
            known["stability_timeout_seconds"] = float(
                known["stability_timeout_seconds"]
            )
            known["max_file_size_mb"] = int(known["max_file_size_mb"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Cấu hình số giây hoặc kích thước file không hợp lệ.") from exc
        return cls(**known)


Settings = AppSettings


class ConfigManager:
    """Nạp/lưu settings UTF-8 bằng phép thay thế file nguyên tử."""

    def __init__(
        self,
        data_root: str | Path | AppPaths | None = None,
        *,
        paths: AppPaths | None = None,
    ) -> None:
        if isinstance(data_root, AppPaths):
            if paths is not None:
                raise TypeError("Không truyền đồng thời data_root AppPaths và paths.")
            paths = data_root
        if paths is not None:
            self._bootstrap_paths = paths
        elif data_root is not None:
            self._bootstrap_paths = AppPaths.from_data_root(data_root)
        else:
            self._bootstrap_paths = AppPaths.defaults()

    @property
    def settings_path(self) -> Path:
        return self._bootstrap_paths.settings_path

    def load(self) -> AppSettings:
        self._bootstrap_paths.ensure_directories()
        if not self.settings_path.exists():
            settings = AppSettings(
                data_root=self._bootstrap_paths.data_root,
                inbox_dir=self._bootstrap_paths.inbox_dir,
                browser_profile_dir=self._bootstrap_paths.browser_profile_dir,
            )
            self.save(settings)
            return settings
        try:
            text = self.settings_path.read_text(encoding="utf-8-sig")
            raw = json.loads(text)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"Không thể đọc cấu hình tại {self.settings_path}."
            ) from exc
        if not isinstance(raw, dict):
            raise ValueError("File cấu hình phải chứa một JSON object.")
        settings = AppSettings.from_dict(raw, fallback_paths=self._bootstrap_paths)
        settings.paths.ensure_directories()
        return settings

    def save(self, settings: AppSettings) -> Path:
        target = self.settings_path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            settings.to_dict(),
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ).encode("utf-8")
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target)
            temp_path = None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        settings.paths.ensure_directories()
        return target

    load_settings = load
    save_settings = save


def load_settings(data_root: str | Path | None = None) -> AppSettings:
    return ConfigManager(data_root).load()


def save_settings(
    settings: AppSettings,
    data_root: str | Path | None = None,
) -> Path:
    manager = ConfigManager(data_root or settings.data_root)
    return manager.save(settings)


def max_file_size_bytes(settings: AppSettings | None = None) -> int:
    return settings.max_file_size_bytes if settings else DEFAULT_MAX_FILE_SIZE_BYTES

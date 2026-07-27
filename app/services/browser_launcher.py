"""Mở GPT Custom bằng hồ sơ trình duyệt riêng.

Module này chỉ khởi chạy trình duyệt. Nó không đăng nhập tự động, không đọc
cookie và không điều khiển nội dung trang web.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices

LOGGER = logging.getLogger(__name__)

_AUTO_PREFERENCES = {"auto", "automatic", "tự động", "tu dong"}
_CHROME_PREFERENCES = {"chrome", "google chrome"}
_EDGE_PREFERENCES = {"edge", "microsoft edge", "msedge"}
_DEFAULT_PREFERENCES = {
    "default",
    "windows",
    "windows default",
    "mặc định",
    "mặc định windows",
    "mac dinh",
    "mac dinh windows",
}


class InvalidBrowserUrlError(ValueError):
    """URL không đáp ứng yêu cầu http/https."""


@dataclass(frozen=True, slots=True)
class BrowserExecutable:
    """Một trình duyệt Chromium tìm thấy trên máy."""

    name: str
    path: Path


@dataclass(frozen=True, slots=True)
class BrowserLaunchResult:
    """Kết quả mở URL để UI có thể hiển thị cảnh báo thân thiện."""

    success: bool
    browser_name: str
    executable_path: Path | None = None
    used_default_browser: bool = False
    warning: str | None = None
    pid: int | None = None

    @property
    def fallback_used(self) -> bool:
        """Alias diễn đạt rõ trường hợp phải dùng trình duyệt Windows."""

        return self.used_default_browser and self.warning is not None

    @property
    def message(self) -> str:
        """Thông điệp ngắn phù hợp để đưa lên giao diện."""

        if self.warning:
            return self.warning
        if self.success:
            return f"Đã mở trợ lý GPT bằng {self.browser_name}."
        return "Không thể mở trợ lý GPT."

    def __bool__(self) -> bool:
        return self.success


# Tên ngắn thuận tiện cho mã tích hợp cũ và các adapter UI.
LaunchResult = BrowserLaunchResult


class BrowserLauncher:
    """Tìm Chrome/Edge và mở GPT trong một browser profile độc lập.

    ``settings`` có thể là ``AppSettings``, một mapping, hoặc bỏ trống. Khi
    truyền settings, :meth:`launch` có thể được gọi không tham số.
    """

    def __init__(
        self,
        settings: object | Mapping[str, Any] | None = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._settings = settings
        self._logger = logger or LOGGER

    def update_settings(
        self, settings: object | Mapping[str, Any] | None
    ) -> None:
        """Thay settings dùng cho những lần mở tiếp theo."""

        self._settings = settings

    @staticmethod
    def validate_url(url: str) -> str:
        """Chuẩn hóa và kiểm tra URL GPT.

        Chỉ URL tuyệt đối dùng ``http`` hoặc ``https`` mới được chấp nhận.
        Hàm trả lại chuỗi đã cắt khoảng trắng để caller có thể dùng trực tiếp.
        """

        if not isinstance(url, str):
            raise InvalidBrowserUrlError("URL GPT phải là chuỗi.")

        normalized = url.strip()
        if not normalized:
            raise InvalidBrowserUrlError(
                "Chưa cấu hình URL GPT Custom trong phần Cài đặt."
            )
        if any(character.isspace() for character in normalized):
            raise InvalidBrowserUrlError("URL GPT không được chứa khoảng trắng.")

        try:
            parsed = urlsplit(normalized)
            port = parsed.port
        except ValueError as exc:
            raise InvalidBrowserUrlError("URL GPT không đúng định dạng.") from exc

        if parsed.scheme.casefold() not in {"http", "https"}:
            raise InvalidBrowserUrlError("URL GPT phải bắt đầu bằng http:// hoặc https://.")
        if not parsed.hostname:
            raise InvalidBrowserUrlError("URL GPT phải có tên miền hợp lệ.")
        if parsed.username is not None or parsed.password is not None:
            raise InvalidBrowserUrlError(
                "Không đưa tên đăng nhập hoặc mật khẩu vào URL GPT."
            )
        if port is not None and not 1 <= port <= 65535:
            raise InvalidBrowserUrlError("Cổng trong URL GPT không hợp lệ.")

        return normalized

    @classmethod
    def detect_browsers(cls) -> dict[str, Path]:
        """Tự dò Chrome và Edge ở PATH, registry và thư mục Windows phổ biến."""

        found: dict[str, Path] = {}
        for name in ("chrome", "edge"):
            for candidate in cls._browser_candidates(name):
                try:
                    resolved = candidate.expanduser().resolve(strict=True)
                except (OSError, RuntimeError):
                    continue
                if resolved.is_file():
                    found[name] = resolved
                    break
        return found

    @classmethod
    def autodetect_executable(
        cls, preference: str = "auto"
    ) -> BrowserExecutable | None:
        """Trả về executable phù hợp với lựa chọn trình duyệt."""

        normalized = cls._normalize_preference(preference)
        if normalized == "default":
            return None

        detected = cls.detect_browsers()
        order = ("chrome", "edge") if normalized == "auto" else (normalized,)
        for name in order:
            path = detected.get(name)
            if path is not None:
                return BrowserExecutable(cls._display_name(name), path)
        return None

    @classmethod
    def find_browser(
        cls, preference: str = "auto"
    ) -> Path | None:
        """API rút gọn, chỉ trả đường dẫn executable đã tự dò."""

        detected = cls.autodetect_executable(preference)
        return detected.path if detected is not None else None

    # Alias thuận tiện cho controller của UI.
    detect = detect_browsers

    def launch(
        self,
        url: str | None = None,
        preference: str | None = None,
        executable_path: str | Path | None = None,
        profile_dir: str | Path | None = None,
        **aliases: object,
    ) -> BrowserLaunchResult:
        """Mở URL và trả về kết quả, tự fallback sang trình duyệt mặc định.

        Các alias ``browser_preference``, ``browser_executable`` và
        ``browser_profile_dir`` được hỗ trợ để controller có thể truyền trực
        tiếp dữ liệu từ form Cài đặt.
        """

        url = self._coalesce(
            url,
            aliases.get("gpt_url"),
            self._setting("gpt_url", "url", default=None),
        )
        preference = self._coalesce(
            preference,
            aliases.get("browser_preference"),
            self._setting(
                "browser_preference",
                "preferred_browser",
                "browser",
                default="auto",
            ),
        )
        executable_path = self._coalesce(
            executable_path,
            aliases.get("browser_executable"),
            self._setting(
                "browser_executable",
                "browser_executable_path",
                "executable_path",
                default=None,
            ),
        )
        profile_dir = self._coalesce(
            profile_dir,
            aliases.get("browser_profile_dir"),
            self._setting(
                "browser_profile_dir",
                "profile_dir",
                default=None,
            ),
            self._default_profile_dir(),
        )
        if profile_dir is None or not str(profile_dir).strip():
            profile_dir = self._default_profile_dir()

        validated_url = self.validate_url(str(url) if url is not None else "")
        normalized_preference = self._normalize_preference(
            str(preference or "auto")
        )
        safe_origin = self._safe_origin(validated_url)

        if normalized_preference == "default":
            self._logger.info(
                "Mở GPT bằng trình duyệt mặc định Windows: %s", safe_origin
            )
            return self._open_with_default(validated_url)

        selected, configured_warning = self._select_executable(
            normalized_preference, executable_path
        )
        if selected is None:
            warning = (
                configured_warning
                or "Không tìm thấy trình duyệt đã chọn; đã dùng trình duyệt mặc định Windows."
            )
            self._logger.warning("%s Đích: %s", warning, safe_origin)
            return self._open_with_default(validated_url, warning=warning)

        selected_profile = Path(str(profile_dir)).expanduser()
        try:
            selected_profile.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            warning = (
                "Không thể tạo hồ sơ trình duyệt riêng; "
                "đã dùng trình duyệt mặc định Windows."
            )
            self._logger.exception(
                "Không tạo được browser profile %s: %s",
                selected_profile,
                exc,
            )
            return self._open_with_default(validated_url, warning=warning)

        arguments = [
            f"--user-data-dir={selected_profile.resolve()}",
            "--profile-directory=Default",
            validated_url,
        ]
        self._logger.info(
            "Mở GPT bằng %s với profile riêng: %s",
            selected.name,
            safe_origin,
        )
        try:
            started, pid = self._start_detached(selected.path, arguments)
        except (OSError, RuntimeError) as exc:
            self._logger.exception(
                "Lỗi khởi chạy %s (%s): %s",
                selected.name,
                selected.path,
                exc,
            )
            started, pid = False, None

        if started:
            return BrowserLaunchResult(
                success=True,
                browser_name=selected.name,
                executable_path=selected.path,
                used_default_browser=False,
                pid=pid,
            )

        warning = (
            f"Không mở được {selected.name}; "
            "đã chuyển sang trình duyệt mặc định Windows."
        )
        self._logger.warning("%s Đích: %s", warning, safe_origin)
        return self._open_with_default(validated_url, warning=warning)

    # Các tên gọi rõ nghĩa cho controller và test.
    open_gpt = launch
    launch_gpt = launch
    open_url = launch
    open = launch

    @staticmethod
    def _start_detached(
        executable: Path, arguments: list[str]
    ) -> tuple[bool, int | None]:
        result = QProcess.startDetached(str(executable), arguments)
        if isinstance(result, tuple):
            started = bool(result[0])
            pid = int(result[1]) if started and len(result) > 1 else None
            return started, pid
        return bool(result), None

    def _open_with_default(
        self, url: str, *, warning: str | None = None
    ) -> BrowserLaunchResult:
        try:
            opened = bool(QDesktopServices.openUrl(QUrl(url)))
        except (OSError, RuntimeError) as exc:
            self._logger.exception(
                "Không gọi được trình duyệt mặc định Windows: %s", exc
            )
            opened = False

        if opened:
            return BrowserLaunchResult(
                success=True,
                browser_name="Trình duyệt mặc định Windows",
                used_default_browser=True,
                warning=warning,
            )

        failure = "Windows không thể mở URL. Hãy kiểm tra trình duyệt mặc định."
        if warning:
            failure = f"{warning} {failure}"
        self._logger.error("Không thể mở GPT bằng trình duyệt mặc định.")
        return BrowserLaunchResult(
            success=False,
            browser_name="Trình duyệt mặc định Windows",
            used_default_browser=True,
            warning=failure,
        )

    def _select_executable(
        self,
        preference: str,
        configured_path: str | Path | None,
    ) -> tuple[BrowserExecutable | None, str | None]:
        warning: str | None = None
        if configured_path is not None and str(configured_path).strip():
            configured = Path(str(configured_path).strip()).expanduser()
            try:
                resolved = configured.resolve(strict=True)
            except (OSError, RuntimeError):
                warning = (
                    "Đường dẫn trình duyệt đã cấu hình không tồn tại; "
                    "ứng dụng đã thử tự dò trình duyệt."
                )
                self._logger.warning(
                    "Executable trình duyệt đã cấu hình không tồn tại: %s",
                    configured,
                )
            else:
                if resolved.is_file():
                    return (
                        BrowserExecutable(
                            self._infer_browser_name(resolved), resolved
                        ),
                        None,
                    )
                warning = (
                    "Đường dẫn trình duyệt đã cấu hình không phải là file; "
                    "ứng dụng đã thử tự dò trình duyệt."
                )

        detected = self.autodetect_executable(preference)
        return detected, warning

    def _setting(self, *names: str, default: object) -> object:
        settings = self._settings
        if settings is None:
            return default
        if isinstance(settings, Mapping):
            for name in names:
                value = settings.get(name)
                if value is not None:
                    return value
            return default
        for name in names:
            value = getattr(settings, name, None)
            if value is not None:
                return value
        return default

    @staticmethod
    def _coalesce(*values: object) -> Any:
        for value in values:
            if value is not None:
                return value
        return None

    @staticmethod
    def _normalize_preference(preference: str) -> str:
        normalized = preference.strip().casefold()
        if normalized in _AUTO_PREFERENCES:
            return "auto"
        if normalized in _CHROME_PREFERENCES:
            return "chrome"
        if normalized in _EDGE_PREFERENCES:
            return "edge"
        if normalized in _DEFAULT_PREFERENCES:
            return "default"
        LOGGER.warning(
            "Lựa chọn trình duyệt không nhận diện được %r; dùng Tự động.",
            preference,
        )
        return "auto"

    @classmethod
    def _browser_candidates(cls, name: str) -> list[Path]:
        executable_name = "chrome.exe" if name == "chrome" else "msedge.exe"
        candidates: list[Path] = []

        path_names = (
            ("chrome", "chrome.exe", "google-chrome", "google-chrome.exe")
            if name == "chrome"
            else ("msedge", "msedge.exe", "microsoft-edge")
        )
        for path_name in path_names:
            discovered = shutil.which(path_name)
            if discovered:
                candidates.append(Path(discovered))

        if sys.platform == "win32":
            candidates.extend(cls._registry_candidates(executable_name))

        program_files = [
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        relative = (
            Path("Google/Chrome/Application/chrome.exe")
            if name == "chrome"
            else Path("Microsoft/Edge/Application/msedge.exe")
        )
        for root in program_files:
            if root:
                candidates.append(Path(root) / relative)

        return cls._deduplicate_paths(candidates)

    @staticmethod
    def _registry_candidates(executable_name: str) -> list[Path]:
        try:
            import winreg
        except ImportError:
            return []

        key_path = (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
            rf"\{executable_name}"
        )
        roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
        views = (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
        candidates: list[Path] = []
        for root in roots:
            for view in views:
                try:
                    with winreg.OpenKey(
                        root, key_path, 0, winreg.KEY_READ | view
                    ) as key:
                        value, _ = winreg.QueryValueEx(key, None)
                except OSError:
                    continue
                if value:
                    candidates.append(Path(str(value)))
        return candidates

    @staticmethod
    def _deduplicate_paths(paths: list[Path]) -> list[Path]:
        unique: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            key = os.path.normcase(os.path.abspath(str(path)))
            if key not in seen:
                seen.add(key)
                unique.append(path)
        return unique

    @staticmethod
    def _display_name(name: str) -> str:
        return "Google Chrome" if name == "chrome" else "Microsoft Edge"

    @classmethod
    def _infer_browser_name(cls, executable: Path) -> str:
        stem = executable.stem.casefold()
        if "edge" in stem:
            return cls._display_name("edge")
        if "chrome" in stem or "chromium" in stem:
            return cls._display_name("chrome")
        return executable.stem

    @staticmethod
    def _safe_origin(url: str) -> str:
        parsed = urlsplit(url)
        return f"{parsed.scheme}://{parsed.hostname or ''}"

    @staticmethod
    def _default_profile_dir() -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return (
                Path(local_app_data)
                / "Kikai"
                / "TroLyDuLieuQuyetToan"
                / "BrowserProfile"
            )
        return (
            Path.home()
            / "AppData"
            / "Local"
            / "Kikai"
            / "TroLyDuLieuQuyetToan"
            / "BrowserProfile"
        )


def validate_browser_url(url: str) -> str:
    """Hàm tiện ích công khai cho validation form Cài đặt."""

    return BrowserLauncher.validate_url(url)


__all__ = [
    "BrowserExecutable",
    "BrowserLaunchResult",
    "BrowserLauncher",
    "InvalidBrowserUrlError",
    "LaunchResult",
    "validate_browser_url",
]

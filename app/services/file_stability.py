"""Chờ file tải xuống ngừng thay đổi trước khi đọc."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event

from app.constants import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_STABILITY_TIMEOUT_SECONDS,
    DEFAULT_STABLE_SECONDS,
    TEMPORARY_FILE_SUFFIXES,
)
from app.models import FileStabilityResult


class FileStabilityError(RuntimeError):
    """File không thể đạt trạng thái đọc an toàn."""


class FileTooLargeError(FileStabilityError):
    """File vượt giới hạn cấu hình."""


class StabilityTimeoutError(FileStabilityError):
    """Hết thời gian nhưng size/mtime vẫn thay đổi hoặc file chưa xuất hiện."""


class FileStabilityCancelledError(FileStabilityError):
    """Tác vụ bị hủy khi watcher đang dừng."""


def is_temporary_file(path: str | Path) -> bool:
    candidate = Path(path)
    name = candidate.name.lower()
    return candidate.name.startswith("~$") or any(
        name.endswith(suffix) for suffix in TEMPORARY_FILE_SUFFIXES
    )


class FileStabilityChecker:
    def __init__(
        self,
        stable_seconds: float = DEFAULT_STABLE_SECONDS,
        timeout_seconds: float = DEFAULT_STABILITY_TIMEOUT_SECONDS,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if stable_seconds < 0:
            raise ValueError("stable_seconds không được âm.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds phải lớn hơn 0.")
        if timeout_seconds < stable_seconds:
            raise ValueError("timeout_seconds phải lớn hơn hoặc bằng stable_seconds.")
        if poll_interval <= 0:
            raise ValueError("poll_interval phải lớn hơn 0.")
        if max_size_bytes <= 0:
            raise ValueError("max_size_bytes phải lớn hơn 0.")
        self.stable_seconds = stable_seconds
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval
        self.max_size_bytes = max_size_bytes
        self._clock = clock
        self._sleep = sleeper

    def wait(
        self,
        path: str | Path,
        *,
        cancel_event: Event | None = None,
    ) -> FileStabilityResult:
        candidate = Path(path)
        if is_temporary_file(candidate):
            raise FileStabilityError("Bỏ qua file tải xuống có hậu tố tạm.")

        started = self._clock()
        deadline = started + self.timeout_seconds
        last_signature: tuple[int, int] | None = None
        stable_since: float | None = None
        last_reason = "file chưa tồn tại"

        while True:
            now = self._clock()
            if cancel_event is not None and cancel_event.is_set():
                raise FileStabilityCancelledError("Đã hủy chờ file ổn định.")

            try:
                stat = candidate.stat()
                if not candidate.is_file():
                    last_reason = "đường dẫn không phải file"
                    signature = None
                else:
                    if stat.st_size > self.max_size_bytes:
                        raise FileTooLargeError(
                            f"File vượt giới hạn {self.max_size_bytes} byte."
                        )
                    signature = (stat.st_size, stat.st_mtime_ns)
                    # Thử mở thực sự; trên Windows thao tác này cũng bắt được nhiều
                    # trường hợp browser còn khóa độc quyền.
                    with candidate.open("rb") as handle:
                        handle.read(1)
                    if signature == last_signature:
                        if stable_since is None:
                            stable_since = now
                        if now - stable_since >= self.stable_seconds:
                            return FileStabilityResult(
                                path=candidate,
                                size=signature[0],
                                mtime_ns=signature[1],
                                elapsed_seconds=now - started,
                            )
                    else:
                        last_signature = signature
                        stable_since = now
                    last_reason = "kích thước hoặc thời gian sửa đổi còn thay đổi"
            except FileTooLargeError:
                raise
            except (FileNotFoundError, PermissionError, OSError) as exc:
                last_signature = None
                stable_since = None
                last_reason = str(exc) or type(exc).__name__

            remaining = deadline - self._clock()
            if remaining <= 0:
                raise StabilityTimeoutError(
                    f"File không ổn định sau {self.timeout_seconds:g} giây "
                    f"({last_reason})."
                )
            self._sleep(min(self.poll_interval, remaining))

    wait_until_stable = wait


def wait_until_stable(
    path: str | Path,
    stable_seconds: float = DEFAULT_STABLE_SECONDS,
    timeout_seconds: float = DEFAULT_STABILITY_TIMEOUT_SECONDS,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    max_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
    *,
    cancel_event: Event | None = None,
    raise_on_error: bool = False,
) -> bool:
    """API bool tiện cho watcher/test; tùy chọn ném lỗi để lấy nguyên nhân."""

    checker = FileStabilityChecker(
        stable_seconds=stable_seconds,
        timeout_seconds=timeout_seconds,
        poll_interval=poll_interval,
        max_size_bytes=max_size_bytes,
    )
    try:
        checker.wait(path, cancel_event=cancel_event)
    except FileStabilityError:
        if raise_on_error:
            raise
        return False
    return True


def file_sha256(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Tiện ích streaming đặt gần luồng file; BatchService cũng xuất alias này."""

    import hashlib

    if chunk_size <= 0:
        raise ValueError("chunk_size phải lớn hơn 0.")
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()

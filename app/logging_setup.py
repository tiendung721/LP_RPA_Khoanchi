"""Thiết lập logging xoay vòng và hook lỗi toàn cục."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

from app.config import AppPaths

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    target: AppPaths | str | Path,
    *,
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> Path:
    """Cấu hình root logger idempotent và trả đường dẫn log chính."""

    if isinstance(target, AppPaths):
        log_path = target.log_path
    else:
        path = Path(target)
        log_path = path if path.suffix.lower() == ".log" else path / "app.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    resolved = log_path.resolve()

    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler):
            try:
                if Path(handler.baseFilename).resolve() == resolved:
                    handler.setLevel(level)
                    handler.setFormatter(formatter)
                    return log_path
            except (OSError, ValueError):
                continue

    handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    root.addHandler(handler)
    return log_path


def install_exception_hook(
    on_user_error: Callable[[str], None] | None = None,
) -> Callable[[type[BaseException], BaseException, TracebackType | None], None]:
    """Ghi traceback đầy đủ; callback chỉ nhận thông báo tiếng Việt ngắn."""

    logger = logging.getLogger(__name__)
    previous_hook = sys.excepthook

    def exception_hook(
        exception_type: type[BaseException],
        exception: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        if issubclass(exception_type, KeyboardInterrupt):
            previous_hook(exception_type, exception, traceback)
            return
        logger.critical(
            "Lỗi chưa được xử lý",
            exc_info=(exception_type, exception, traceback),
        ) 
        if on_user_error is not None:
            try:
                on_user_error(
                    "Ứng dụng gặp lỗi không mong đợi. Vui lòng xem mục Nhật ký."
                )
            except Exception:
                logger.exception("Không thể hiển thị thông báo lỗi thân thiện")

    sys.excepthook = exception_hook
    return exception_hook


def read_log_tail(log_path: str | Path, *, max_lines: int = 500) -> str:
    """Đọc phần cuối log, trả chuỗi rỗng nếu file chưa được tạo."""

    if max_lines <= 0:
        return ""
    path = Path(log_path)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        return ""
    except OSError:
        logging.getLogger(__name__).exception("Không thể đọc file log %s", path)
        return ""
    return "".join(lines[-max_lines:])

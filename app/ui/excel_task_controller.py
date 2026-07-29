"""Điều phối tác vụ Excel nền qua một worker duy nhất.

Controller không phụ thuộc model/service cụ thể. Service chỉ cần cung cấp
``analyze(progress_callback=...)`` và ``apply(plan, resolutions,
progress_callback=...)``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from threading import RLock
from typing import Any

from PySide6.QtCore import QObject, Signal


def _value(source: Any, *names: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, Mapping):
        for name in names:
            if name in source:
                return source[name]
        return default
    for name in names:
        if hasattr(source, name):
            value = getattr(source, name)
            if callable(value) and name.startswith(("is_", "has_", "needs_", "requires_")):
                value = value()
            return getattr(value, "value", value)
    return default


def _items(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return tuple(value.values())
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(value)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


class ExcelTaskController(QObject):
    """Chạy đồng bộ/nhập khoản chi tuần tự và chuyển kết quả về Qt UI.

    Signal công khai:

    - ``started(str operation)``
    - ``progress(str operation, str message)``
    - ``analysis_ready(object plan)``
    - ``completed(object result)``
    - ``failed(object exception)``
    - ``finished(str operation)``
    """

    started = Signal(str)
    progress = Signal(str, str)
    analysis_ready = Signal(object)
    completed = Signal(object)
    failed = Signal(object)
    finished = Signal(str)

    SYNC_OPERATION = "sync"
    POSTING_OPERATION = "posting"

    def __init__(
        self,
        daily_sync_service: Any | None = None,
        expense_posting_service: Any | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.daily_sync_service = daily_sync_service
        self.expense_posting_service = expense_posting_service
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="excel-worker",
        )
        self._state_lock = RLock()
        self._active_operation: str | None = None
        self._phase = "idle"
        self._future: Future[Any] | None = None
        self._waiting_plan: Any | None = None
        self._closed = False

    @classmethod
    def normalize_operation(cls, operation: Any) -> str:
        value = str(getattr(operation, "value", operation) or "").casefold()
        if value in {"sync", "daily_sync", "sync_daily", "daily"}:
            return cls.SYNC_OPERATION
        if value in {
            "posting",
            "post",
            "expense_posting",
            "post_expenses",
            "expenses",
        }:
            return cls.POSTING_OPERATION
        raise ValueError(f"Nghiệp vụ Excel không hợp lệ: {operation!r}")

    @property
    def active_operation(self) -> str | None:
        with self._state_lock:
            return self._active_operation

    @property
    def is_busy(self) -> bool:
        return self.active_operation is not None

    @property
    def phase(self) -> str:
        with self._state_lock:
            return self._phase

    def update_services(
        self,
        *,
        daily_sync_service: Any | None = None,
        expense_posting_service: Any | None = None,
    ) -> None:
        """Thay service sau khi settings/runtime được cập nhật."""

        if self.is_busy:
            raise RuntimeError("Không thể thay dịch vụ khi tác vụ Excel đang chạy.")
        if daily_sync_service is not None:
            self.daily_sync_service = daily_sync_service
        if expense_posting_service is not None:
            self.expense_posting_service = expense_posting_service

    def submit(
        self,
        operation: Any,
        task: Callable[..., Any],
        *args: Any,
        with_progress: bool = False,
        **kwargs: Any,
    ) -> Future[Any]:
        """Chạy một callable độc quyền trên Excel worker.

        Khi ``with_progress=True``, controller tự truyền keyword
        ``progress_callback`` nếu caller chưa truyền.
        """

        normalized = self.normalize_operation(operation)
        self._reserve(normalized, "running")
        self.started.emit(normalized)
        call_kwargs = dict(kwargs)
        if with_progress:
            call_kwargs.setdefault(
                "progress_callback",
                self._progress_callback(normalized),
            )
        try:
            future = self._executor.submit(task, *args, **call_kwargs)
        except BaseException:
            self._release(normalized)
            self.finished.emit(normalized)
            raise
        self._future = future
        future.add_done_callback(
            lambda done, op=normalized: self._complete_one_shot(op, done)
        )
        return future

    def start_sync(self, **analyze_kwargs: Any) -> Future[Any]:
        return self._start_analysis(
            self.SYNC_OPERATION,
            self.daily_sync_service,
            analyze_kwargs,
        )

    analyze_sync = start_sync
    submit_sync = start_sync

    def start_posting(self, **analyze_kwargs: Any) -> Future[Any]:
        return self._start_analysis(
            self.POSTING_OPERATION,
            self.expense_posting_service,
            analyze_kwargs,
        )

    analyze_posting = start_posting
    submit_posting = start_posting

    def start(self, operation: Any, **analyze_kwargs: Any) -> Future[Any]:
        normalized = self.normalize_operation(operation)
        if normalized == self.SYNC_OPERATION:
            return self.start_sync(**analyze_kwargs)
        return self.start_posting(**analyze_kwargs)

    def _start_analysis(
        self,
        operation: str,
        service: Any,
        analyze_kwargs: Mapping[str, Any],
    ) -> Future[Any]:
        if service is None or not callable(getattr(service, "analyze", None)):
            raise RuntimeError(
                "Dịch vụ đồng bộ Excel chưa được khởi tạo."
                if operation == self.SYNC_OPERATION
                else "Dịch vụ nhập khoản chi chưa được khởi tạo."
            )
        self._reserve(operation, "analyzing")
        self.started.emit(operation)
        kwargs = dict(analyze_kwargs)
        kwargs.setdefault("progress_callback", self._progress_callback(operation))
        try:
            future = self._executor.submit(service.analyze, **kwargs)
        except BaseException:
            self._release(operation)
            self.finished.emit(operation)
            raise
        self._future = future
        future.add_done_callback(
            lambda done, op=operation, owner=service: self._analysis_done(
                op, owner, done
            )
        )
        return future

    def apply_plan(
        self,
        plan: Any,
        resolutions: Any = None,
        *,
        operation: Any | None = None,
    ) -> Future[Any]:
        """Tiếp tục một plan đang chờ dialog hoặc áp dụng plan do caller cung cấp."""

        normalized = (
            self.normalize_operation(operation)
            if operation is not None
            else self._operation_for_plan(plan)
        )
        service = self._service_for(normalized)
        if service is None or not callable(getattr(service, "apply", None)):
            raise RuntimeError("Dịch vụ Excel không hỗ trợ áp dụng kế hoạch.")

        with self._state_lock:
            active = self._active_operation
            phase = self._phase
            if active is None:
                self._active_operation = normalized
                self._phase = "applying"
                emit_started = True
            elif active != normalized:
                raise RuntimeError(
                    f"Tác vụ {active!r} đang hoạt động; không thể chạy {normalized!r}."
                )
            elif phase != "waiting_user":
                raise RuntimeError("Kế hoạch Excel chưa ở trạng thái chờ xử lý.")
            else:
                self._phase = "applying"
                emit_started = False
            self._waiting_plan = None

        if emit_started:
            self.started.emit(normalized)
        return self._submit_apply(
            normalized,
            service,
            plan,
            {} if resolutions is None else resolutions,
        )

    continue_with_resolutions = apply_plan
    apply = apply_plan

    def refine_plan(
        self,
        plan: Any,
        resolutions: Any,
        *,
        operation: Any | None = None,
    ) -> Future[Any]:
        """Phân tích lại plan sau lựa chọn dòng/mã phí, vẫn trên worker duy nhất."""

        normalized = (
            self.normalize_operation(operation)
            if operation is not None
            else self._operation_for_plan(plan)
        )
        service = self._service_for(normalized)
        refine = getattr(service, "refine", None)
        if not callable(refine):
            return self.apply_plan(
                plan, resolutions, operation=normalized
            )
        with self._state_lock:
            if (
                self._active_operation != normalized
                or self._phase != "waiting_user"
            ):
                raise RuntimeError("Kế hoạch Excel chưa ở trạng thái chờ xử lý.")
            self._phase = "refining"
            self._waiting_plan = None
        callback = self._progress_callback(normalized)
        try:
            future = self._executor.submit(
                refine,
                plan,
                resolutions,
                progress_callback=callback,
            )
        except BaseException as exc:
            self._finish_failure(normalized, exc)
            raise
        self._future = future
        future.add_done_callback(
            lambda done, op=normalized, owner=service: self._refine_done(
                op, owner, done
            )
        )
        return future

    def cancel_waiting(self) -> bool:
        """Giải phóng controller khi người dùng đóng dialog xung đột."""

        with self._state_lock:
            if self._active_operation is None or self._phase != "waiting_user":
                return False
            operation = self._active_operation
            plan = self._waiting_plan
        service = self._service_for(operation)
        cancel = getattr(service, "cancel", None)
        if plan is not None and callable(cancel):
            try:
                cancel(plan)
            except Exception:
                # Hủy UI không được làm controller mắc kẹt chỉ vì lưu audit lỗi.
                pass
        self._release(operation)
        self.finished.emit(operation)
        return True

    def _analysis_done(
        self,
        operation: str,
        service: Any,
        future: Future[Any],
    ) -> None:
        try:
            plan = future.result()
        except BaseException as exc:
            self._finish_failure(operation, exc)
            return

        if self._requires_user_input(plan):
            with self._state_lock:
                if self._active_operation == operation:
                    self._phase = "waiting_user"
                    self._waiting_plan = plan
            self.analysis_ready.emit(plan)
            return

        if self._analysis_is_terminal(plan):
            apply_method = getattr(service, "apply", None)
            if callable(apply_method):
                self._submit_apply(operation, service, plan, {})
            else:
                self._finish_success(operation, plan)
            return

        self._submit_apply(operation, service, plan, {})

    def _refine_done(
        self,
        operation: str,
        service: Any,
        future: Future[Any],
    ) -> None:
        try:
            plan = future.result()
        except BaseException as exc:
            self._finish_failure(operation, exc)
            return
        if self._requires_user_input(plan):
            with self._state_lock:
                if self._active_operation == operation:
                    self._phase = "waiting_user"
                    self._waiting_plan = plan
            self.analysis_ready.emit(plan)
            return
        self._submit_apply(operation, service, plan, {})

    def _submit_apply(
        self,
        operation: str,
        service: Any,
        plan: Any,
        resolutions: Any,
    ) -> Future[Any]:
        callback = self._progress_callback(operation)
        try:
            future = self._executor.submit(
                service.apply,
                plan,
                resolutions,
                progress_callback=callback,
            )
        except BaseException as exc:
            self._finish_failure(operation, exc)
            raise
        self._future = future
        future.add_done_callback(
            lambda done, op=operation: self._apply_done(op, done)
        )
        return future

    def _apply_done(self, operation: str, future: Future[Any]) -> None:
        try:
            result = future.result()
        except BaseException as exc:
            self._finish_failure(operation, exc)
            return
        self._finish_success(operation, result)

    def _complete_one_shot(
        self,
        operation: str,
        future: Future[Any],
    ) -> None:
        try:
            result = future.result()
        except BaseException as exc:
            self._finish_failure(operation, exc)
            return
        self._finish_success(operation, result)

    def _finish_success(self, operation: str, result: Any) -> None:
        self._release(operation)
        self.completed.emit(result)
        self.finished.emit(operation)

    def _finish_failure(self, operation: str, error: BaseException) -> None:
        self._release(operation)
        self.failed.emit(error)
        self.finished.emit(operation)

    def _reserve(self, operation: str, phase: str) -> None:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("ExcelTaskController đã đóng.")
            if self._active_operation is not None:
                raise RuntimeError(
                    f"Tác vụ {self._active_operation!r} đang hoạt động."
                )
            self._active_operation = operation
            self._phase = phase

    def _release(self, operation: str) -> None:
        with self._state_lock:
            if self._active_operation == operation:
                self._active_operation = None
                self._phase = "idle"
                self._future = None
                self._waiting_plan = None

    def _progress_callback(self, operation: str) -> Callable[..., None]:
        def report(*parts: Any) -> None:
            if not parts:
                return
            message = " ".join(str(part) for part in parts if part is not None)
            if message:
                self.progress.emit(operation, message)

        return report

    def _service_for(self, operation: str) -> Any:
        return (
            self.daily_sync_service
            if operation == self.SYNC_OPERATION
            else self.expense_posting_service
        )

    def _operation_for_plan(self, plan: Any) -> str:
        explicit = _value(plan, "operation", "operation_type")
        if explicit:
            return self.normalize_operation(explicit)
        name = type(plan).__name__.casefold()
        if "post" in name or "expense" in name:
            return self.POSTING_OPERATION
        if "sync" in name:
            return self.SYNC_OPERATION
        active = self.active_operation
        if active is not None:
            return active
        raise ValueError("Không xác định được nghiệp vụ từ kế hoạch Excel.")

    @staticmethod
    def _requires_user_input(plan: Any) -> bool:
        explicit = _value(
            plan,
            "requires_user_input",
            "needs_user_input",
            "needs_resolution",
            default=None,
        )
        if explicit is True:
            return bool(explicit)

        conflicts = _items(
            _value(plan, "conflicts", "unresolved_conflicts", default=())
        )
        if conflicts:
            return True
        if explicit is False:
            return False

        selected = _value(
            plan,
            "selected_sheet_name",
            "sheet_name",
            "selected_month",
            default=None,
        )
        candidates = _items(
            _value(
                plan,
                "month_candidates",
                "sheet_candidates",
                "target_sheet_candidates",
                default=(),
            )
        )
        return selected in (None, "") and len(candidates) > 1

    @staticmethod
    def _analysis_is_terminal(plan: Any) -> bool:
        explicit = _value(
            plan,
            "is_terminal",
            "analysis_complete",
            default=None,
        )
        if explicit is not None:
            return bool(explicit)
        status = str(_value(plan, "status", default="")).split(".")[-1].upper()
        if status in {"NO_CHANGES", "CANCELLED", "FAILED"}:
            return True
        has_changes = _value(plan, "has_changes", default=None)
        return has_changes is False

    def shutdown(
        self,
        wait: bool = True,
        *,
        cancel_futures: bool = False,
    ) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    close = shutdown


__all__ = ["ExcelTaskController"]

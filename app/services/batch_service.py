"""Điều phối tiếp nhận, chống trùng, archive, working copy và snapshot Ready."""

from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from app.config import AppPaths, AppSettings
from app.constants import CANONICAL_JSON_FILENAME, DEFAULT_MAX_FILE_SIZE_BYTES
from app.database import Database
from app.models import (
    BatchDocument,
    BatchMetadata,
    BatchReview,
    BatchStatus,
    DataRow,
    ReceiveResult,
    ValidationResult,
)
from app.repositories.batch_repository import BatchRepository, local_now_iso
from app.schema import coerce_document
from app.services.file_stability import file_sha256, is_temporary_file
from app.services.json_codec import JsonCodec, JsonCodecError
from app.services.validation_service import ValidationService

LOGGER = logging.getLogger(__name__)
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class BatchServiceError(RuntimeError):
    """Lỗi nghiệp vụ có thông điệp phù hợp để controller chuyển cho UI."""


class BatchNotFoundError(BatchServiceError):
    """Không có batch tương ứng trong lịch sử."""


class BatchDataError(BatchServiceError):
    """Working file không thể đọc hoặc ghi an toàn."""


class BatchValidationError(BatchServiceError):
    def __init__(self, message: str, validation: ValidationResult) -> None:
        super().__init__(message)
        self.validation = validation
        self.first_error_row = validation.first_error_row


class SourceFileChangedError(BatchServiceError):
    """File nguồn thay đổi sau lúc tính hash."""


def calculate_sha256(path: str | Path) -> str:
    return file_sha256(path)


class BatchService:
    def __init__(
        self,
        paths: AppPaths | AppSettings | str | Path | BatchRepository,
        repository: BatchRepository | AppPaths | AppSettings | str | Path | None = None,
        *,
        codec: JsonCodec | None = None,
        validation_service: ValidationService | None = None,
        validator: ValidationService | None = None,
        max_file_size_bytes: int | None = None,
        output_write_callback: Callable[[Path], None] | None = None,
    ) -> None:
        # Hỗ trợ cả BatchService(paths, repo) và BatchService(repo, paths).
        if isinstance(paths, BatchRepository):
            actual_repository = paths
            if repository is None:
                raise TypeError("Cần truyền AppPaths khi tham số đầu là repository.")
            actual_paths = self._coerce_paths(repository)
        else:
            actual_paths = self._coerce_paths(paths)
            actual_repository = (
                repository if isinstance(repository, BatchRepository) else None
            )
            if repository is not None and actual_repository is None:
                raise TypeError("repository phải là BatchRepository.")

        actual_paths.ensure_directories()
        self.paths = actual_paths
        self._owns_repository = actual_repository is None
        self.repository = actual_repository or BatchRepository(
            Database(actual_paths.database_path)
        )
        self.codec = codec or JsonCodec()
        self.validation_service = (
            validation_service or validator or ValidationService()
        )
        self.max_file_size_bytes = (
            max_file_size_bytes
            if max_file_size_bytes is not None
            else DEFAULT_MAX_FILE_SIZE_BYTES
        )
        if self.max_file_size_bytes <= 0:
            raise ValueError("Giới hạn kích thước file phải lớn hơn 0.")
        self._output_write_callback = output_write_callback
        self._current_output_batch_id = self._find_current_output_batch_id()

    def set_output_write_callback(
        self, callback: Callable[[Path], None] | None
    ) -> None:
        self._output_write_callback = callback

    def update_paths(self, paths: AppPaths) -> None:
        paths.ensure_directories()
        output_changed = self._path_key(paths.output_dir) != self._path_key(
            self.paths.output_dir
        )
        self.paths = paths
        if output_changed:
            self._current_output_batch_id = self._find_current_output_batch_id()
            self.repository.set_active_batch_id(self._current_output_batch_id)

    @property
    def current_output_batch_id(self) -> int | None:
        return self._current_output_batch_id

    def get_current_output_batch(self) -> BatchMetadata | None:
        batch_id = self._current_output_batch_id
        return self.repository.get_by_id(batch_id) if batch_id is not None else None

    @staticmethod
    def _coerce_paths(
        value: AppPaths | AppSettings | str | Path,
    ) -> AppPaths:
        if isinstance(value, AppPaths):
            return value
        if isinstance(value, AppSettings):
            return value.paths
        return AppPaths.from_data_root(value)

    def receive_file(self, path: str | Path) -> ReceiveResult:
        """Tiếp nhận file ổn định từ Output và giữ bản gốc trong Archive."""

        source = Path(path)
        LOGGER.info("Bắt đầu tiếp nhận file: %s", source.name)
        if is_temporary_file(source):
            raise BatchServiceError("File vẫn mang hậu tố tải xuống tạm thời.")
        if source.suffix.lower() != ".json":
            raise BatchServiceError("Chỉ có thể tiếp nhận file có đuôi .json.")
        try:
            stat_result = source.stat()
        except OSError as exc:
            raise BatchServiceError(f"Không thể truy cập file: {source}.") from exc
        if not source.is_file():
            raise BatchServiceError("Đường dẫn đã chọn không phải là file.")
        if stat_result.st_size > self.max_file_size_bytes:
            raise BatchServiceError(
                "File vượt giới hạn kích thước đã cấu hình."
            )
        if self._is_output_candidate(source) and not self._is_latest_output_candidate(
            source
        ):
            raise BatchServiceError(
                "Đã bỏ qua file cũ vì Output có một file kết quả mới hơn."
            )

        try:
            sha256 = calculate_sha256(source)
        except OSError as exc:
            raise BatchServiceError("Không thể đọc file để tính SHA-256.") from exc
        LOGGER.info("SHA-256 file %s: %s", source.name, sha256)
        duplicate = self.repository.get_by_sha256(sha256)
        if duplicate is not None:
            canonical_source = self._promote_output_file(source)
            duplicate = self.repository.update_batch(
                duplicate.id,
                source_filename=canonical_source.name,
                source_output_path=canonical_source,
            )
            self._current_output_batch_id = duplicate.id
            LOGGER.info(
                "File trùng SHA-256 với batch %s; không tạo batch mới",
                duplicate.id,
            )
            return ReceiveResult(
                batch=duplicate,
                duplicate=True,
                message="File này đã được tiếp nhận trước đó.",
            )

        received_at = local_now_iso()
        placeholder = self.paths.workspace_dir / ".pending"
        try:
            batch = self.repository.create_batch(
                source_filename=source.name,
                source_output_path=source,
                original_archive_path=self.paths.archive_original_dir / ".pending",
                working_path=placeholder,
                sha256=sha256,
                status=BatchStatus.RECEIVED,
                received_at=received_at,
            )
        except sqlite3.IntegrityError:
            # Hai event watchdog có thể đồng thời vượt qua kiểm tra trên.
            duplicate = self.repository.get_by_sha256(sha256)
            if duplicate is None:
                raise BatchServiceError("Không thể tạo metadata cho file JSON.")
            return ReceiveResult(
                batch=duplicate,
                duplicate=True,
                message="File này đã được tiếp nhận trước đó.",
            )

        timestamp = self._filename_timestamp(received_at)
        safe_source_name = self._safe_filename(source.name)
        archive_path = (
            self.paths.archive_original_dir
            / f"{batch.id}__{timestamp}__{safe_source_name}"
        )
        workspace_batch_dir = self.paths.workspace_dir / str(batch.id)
        working_path = workspace_batch_dir / CANONICAL_JSON_FILENAME
        workspace_batch_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._copy_file_atomic(source, archive_path)
            archived_hash = calculate_sha256(archive_path)
            if archived_hash != sha256:
                raise SourceFileChangedError(
                    "File nguồn đã thay đổi trong lúc tiếp nhận; vui lòng thử lại."
                )
            self._copy_file_atomic(archive_path, working_path)
            self._make_writable(working_path)
            self._mark_read_only(archive_path)
            batch = self.repository.update_batch(
                batch.id,
                source_filename=CANONICAL_JSON_FILENAME,
                source_output_path=self._promote_output_file(source),
                original_archive_path=archive_path,
                working_path=working_path,
            )
            self._current_output_batch_id = batch.id
            LOGGER.info(
                "Đã tạo archive %s và working copy %s",
                archive_path,
                working_path,
            )
        except Exception as exc:
            LOGGER.exception("Không thể tạo archive/working cho batch %s", batch.id)
            if archive_path.is_file():
                self._mark_read_only(archive_path)
            metadata = self.repository.update_batch(
                batch.id,
                status=BatchStatus.INVALID,
                original_archive_path=archive_path,
                working_path=working_path,
                error_count=1,
                last_error=str(exc),
            )
            return ReceiveResult(
                batch=metadata,
                duplicate=False,
                message=(
                    "Không thể sao lưu file nguồn an toàn. "
                    "Vui lòng kiểm tra quyền ghi thư mục dữ liệu."
                ),
            )

        try:
            document = self.codec.load(working_path)
        except JsonCodecError as exc:
            LOGGER.warning("Batch %s không parse/schema được: %s", batch.id, exc)
            rejected_path = (
                self.paths.rejected_dir
                / f"{batch.id}__{timestamp}__{safe_source_name}"
            )
            try:
                self._copy_file_atomic(archive_path, rejected_path)
                self._mark_read_only(rejected_path)
            except OSError:
                LOGGER.exception("Không thể tạo bản Rejected cho batch %s", batch.id)
            metadata = self.repository.update_batch(
                batch.id,
                status=BatchStatus.INVALID,
                error_count=1,
                last_error=str(exc),
            )
            return ReceiveResult(
                batch=metadata,
                duplicate=False,
                message=(
                    "File JSON không đọc được hoặc sai cấu trúc gốc. "
                    "Vui lòng kiểm tra file trong mục Lịch sử."
                ),
            )

        validation = self.validation_service.validate_document(document)
        batch = self.repository.update_batch(
            batch.id,
            last_saved_at=local_now_iso(),
            row_count=validation.summary.total_rows,
            valid_count=validation.summary.valid_count,
            warning_count=validation.summary.warning_count,
            error_count=validation.error_count,
            total_amount=validation.summary.total_amount,
            last_error=None,
        )
        self._activate_if_appropriate(batch)
        review = BatchReview(batch, document, validation)
        LOGGER.info(
            "Đã tiếp nhận batch %s: %s dòng, %s cảnh báo, %s lỗi",
            batch.id,
            batch.row_count,
            batch.warning_count,
            batch.error_count,
        )
        return ReceiveResult(
            batch=batch,
            duplicate=False,
            message="Đã tiếp nhận file JSON thành công.",
            review=review,
        )

    ingest_file = receive_file
    process_file = receive_file
    receive = receive_file

    def load_batch(self, batch_id: int) -> BatchReview:
        metadata = self._require_batch(batch_id)
        try:
            document = self.codec.load(metadata.working_path)
        except JsonCodecError as exc:
            self.repository.update_batch(
                batch_id,
                status=BatchStatus.INVALID,
                error_count=max(1, metadata.error_count),
                last_error=str(exc),
            )
            raise BatchDataError(
                "Bản làm việc không còn là JSON có cấu trúc hợp lệ."
            ) from exc
        validation = self.validation_service.validate_document(document)
        new_status = (
            BatchStatus.REVIEWING
            if metadata.status is BatchStatus.RECEIVED
            else metadata.status
        )
        metadata = self.repository.update_batch(
            batch_id,
            status=new_status,
            last_opened_at=local_now_iso(),
            row_count=validation.summary.total_rows,
            valid_count=validation.summary.valid_count,
            warning_count=validation.summary.warning_count,
            error_count=validation.error_count,
            total_amount=validation.summary.total_amount,
            last_error=None,
        )
        if batch_id == self._current_output_batch_id:
            self.repository.set_active_batch_id(batch_id)
        return BatchReview(metadata, document, validation)

    open_batch = load_batch

    def save_working(
        self,
        batch_id: int,
        document: BatchDocument
        | dict[str, Any]
        | Iterable[DataRow | Sequence[Any]],
    ) -> BatchReview:
        metadata = self._require_batch(batch_id)
        normalized = coerce_document(document)
        try:
            self.codec.dump_atomic(
                metadata.working_path,
                normalized,
                create_backup=True,
                validate=True,
            )
            reloaded = self.codec.load(metadata.working_path)
        except (JsonCodecError, OSError) as exc:
            LOGGER.exception("Không thể lưu working file batch %s", batch_id)
            raise BatchDataError(
                "Không thể lưu bản đang chỉnh sửa an toàn."
            ) from exc
        revalidation = self.validation_service.validate_document(reloaded)
        metadata = self.repository.mark_saved(
            batch_id,
            revalidation.summary,
            status=BatchStatus.REVIEWING,
            error_count=revalidation.error_count,
        )
        if batch_id == self._current_output_batch_id:
            self.repository.set_active_batch_id(batch_id)
        self._sync_active_batch_to_output(batch_id, metadata.working_path)
        LOGGER.info("Đã lưu working file batch %s bằng phép ghi nguyên tử", batch_id)
        return BatchReview(metadata, reloaded, revalidation)

    save_working_copy = save_working
    save_batch = save_working

    def confirm_batch(
        self,
        batch_id: int,
        document: BatchDocument
        | dict[str, Any]
        | Iterable[DataRow | Sequence[Any]]
        | None = None,
    ) -> BatchReview:
        if document is None:
            loaded = self.load_batch(batch_id)
            document_to_save = loaded.document
        else:
            document_to_save = coerce_document(document)

        saved = self.save_working(batch_id, document_to_save)
        if saved.validation.has_errors:
            raise BatchValidationError(
                "Không thể xác nhận vì lô vẫn còn lỗi chặn.",
                saved.validation,
            )

        ready_path = self._new_ready_path(batch_id)
        try:
            self.codec.dump_atomic(
                ready_path,
                saved.document,
                create_backup=False,
                validate=True,
            )
            ready_validation = self.validation_service.validate_document(
                self.codec.load(ready_path)
            )
            if ready_validation.has_errors:
                raise BatchValidationError(
                    "Snapshot Ready không vượt qua kiểm tra đọc lại.",
                    ready_validation,
                )
            self._mark_read_only(ready_path)
            metadata = self.repository.mark_ready(
                batch_id,
                ready_path,
                ready_validation.summary,
            )
        except Exception:
            LOGGER.exception("Không thể tạo snapshot Ready cho batch %s", batch_id)
            # File vừa tạo chưa được công bố trong database; dọn orphan nếu có.
            try:
                self._make_writable(ready_path)
                ready_path.unlink(missing_ok=True)
            except OSError:
                LOGGER.exception("Không thể dọn snapshot Ready chưa hoàn tất")
            raise

        LOGGER.info("Đã xác nhận batch %s tại %s", batch_id, ready_path)
        return BatchReview(metadata, saved.document, ready_validation)

    confirm = confirm_batch
    finalize_batch = confirm_batch

    def reopen_batch(self, batch_id: int) -> BatchReview:
        review = self.load_batch(batch_id)
        if review.metadata.status is BatchStatus.READY:
            metadata = self.repository.update_batch(
                batch_id,
                status=BatchStatus.REVIEWING,
                last_opened_at=local_now_iso(),
            )
            review = BatchReview(metadata, review.document, review.validation)
        if batch_id == self._current_output_batch_id:
            self.repository.set_active_batch_id(batch_id)
        return review

    def restore_active_batch(self) -> BatchReview | None:
        candidate = self.repository.restore_active_batch()
        while candidate is not None:
            try:
                return self.load_batch(candidate.id)
            except BatchDataError:
                LOGGER.exception(
                    "Không thể khôi phục working file batch %s", candidate.id
                )
                self.repository.set_active_batch_id(None)
                candidate = next(
                    (
                        item
                        for item in self.repository.list_recoverable()
                        if item.id != candidate.id and item.working_path.is_file()
                    ),
                    None,
                )
                if candidate is not None:
                    self.repository.set_active_batch_id(candidate.id)
        return None

    restore = restore_active_batch

    def set_active_batch(self, batch_id: int | None) -> None:
        if batch_id is not None:
            self._require_batch(batch_id)
        self.repository.set_active_batch_id(batch_id)

    def get_active_batch(self) -> BatchMetadata | None:
        batch_id = self.repository.get_active_batch_id()
        return self.repository.get_by_id(batch_id) if batch_id is not None else None

    def get_batch(self, batch_id: int) -> BatchMetadata | None:
        return self.repository.get_by_id(batch_id)

    def list_batches(
        self,
        *,
        search: str | None = None,
        status: BatchStatus | str | None = None,
        limit: int | None = None,
    ) -> list[BatchMetadata]:
        return self.repository.list_batches(
            search=search,
            status=status,
            limit=limit,
        )

    def validate_batch(self, batch_id: int) -> ValidationResult:
        return self.load_batch(batch_id).validation

    def close(self) -> None:
        if self._owns_repository:
            self.repository.database.close()

    def _activate_if_appropriate(self, new_batch: BatchMetadata) -> None:
        # File Output mới luôn là phiên bản hiện hành. Cửa sổ review cũ vẫn giữ
        # working copy riêng và không được đồng bộ ngược ra Output.
        self.repository.set_active_batch_id(new_batch.id)

    def _require_batch(self, batch_id: int) -> BatchMetadata:
        metadata = self.repository.get_by_id(batch_id)
        if metadata is None:
            raise BatchNotFoundError(f"Không tìm thấy batch {batch_id}.")
        return metadata

    def _new_ready_path(self, batch_id: int) -> Path:
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        candidate = (
            self.paths.ready_dir
            / f"{batch_id}__{timestamp}__{CANONICAL_JSON_FILENAME}"
        )
        counter = 1
        while candidate.exists():
            candidate = (
                self.paths.ready_dir
                / (
                    f"{batch_id}__{timestamp}_{counter:02d}"
                    f"__{CANONICAL_JSON_FILENAME}"
                )
            )
            counter += 1
        return candidate

    @staticmethod
    def _filename_timestamp(iso_value: str) -> str:
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError:
            parsed = datetime.now().astimezone()
        return parsed.strftime("%Y%m%d_%H%M%S")

    @staticmethod
    def _safe_filename(filename: str) -> str:
        safe = _UNSAFE_FILENAME_RE.sub("_", Path(filename).name).strip(" .")
        return safe or CANONICAL_JSON_FILENAME

    def _promote_output_file(self, source: Path) -> Path:
        """Chỉ giữ candidate mới và chuẩn hóa tên trong thư mục Output."""

        try:
            in_output = source.resolve().parent == self.paths.output_dir.resolve()
        except OSError:
            in_output = False
        if not in_output:
            return source

        canonical = self.paths.output_dir / CANONICAL_JSON_FILENAME
        for candidate in self.paths.output_dir.glob("ket_qua_boc_tach*.json"):
            try:
                same_as_source = candidate.resolve() == source.resolve()
            except OSError:
                same_as_source = candidate == source
            if same_as_source:
                continue
            try:
                candidate.unlink(missing_ok=True)
                LOGGER.info("Đã dọn file Output cũ: %s", candidate)
            except OSError as exc:
                raise BatchServiceError(
                    f"Không thể xóa file Output cũ đang bị khóa: {candidate.name}"
                ) from exc

        if source != canonical:
            try:
                os.replace(source, canonical)
            except OSError as exc:
                raise BatchServiceError(
                    f"Không thể chuẩn hóa file Output thành {CANONICAL_JSON_FILENAME}."
                ) from exc
        self._notify_output_written(canonical)
        return canonical

    def _find_current_output_batch_id(self) -> int | None:
        canonical = self.paths.output_dir / CANONICAL_JSON_FILENAME
        try:
            if not canonical.is_file():
                return None
            sha256 = calculate_sha256(canonical)
        except OSError:
            LOGGER.warning(
                "Không thể nhận diện batch tương ứng với Output hiện hành: %s",
                canonical,
            )
            return None
        metadata = self.repository.get_by_sha256(sha256)
        return metadata.id if metadata is not None else None

    def _is_output_candidate(self, source: Path) -> bool:
        try:
            return source.resolve().parent == self.paths.output_dir.resolve()
        except OSError:
            return False

    def _is_latest_output_candidate(self, source: Path) -> bool:
        try:
            candidates = [
                candidate
                for candidate in self.paths.output_dir.glob(
                    "ket_qua_boc_tach*.json"
                )
                if candidate.is_file()
            ]
            latest = max(
                candidates,
                key=lambda candidate: (
                    candidate.stat().st_mtime_ns,
                    candidate.name.casefold(),
                ),
            )
        except (OSError, ValueError):
            return True
        return self._path_key(latest) == self._path_key(source)

    def _sync_active_batch_to_output(self, batch_id: int, working_path: Path) -> None:
        if self._current_output_batch_id != batch_id:
            LOGGER.info(
                "Batch %s không còn là Output hiện hành; chỉ lưu working copy.",
                batch_id,
            )
            return
        output_path = self.paths.output_dir / CANONICAL_JSON_FILENAME
        self._copy_file_atomic(working_path, output_path)
        self._notify_output_written(output_path)
        self.repository.update_batch(
            batch_id,
            source_filename=CANONICAL_JSON_FILENAME,
            source_output_path=output_path,
        )

    def _notify_output_written(self, path: Path) -> None:
        callback = self._output_write_callback
        if callback is not None:
            try:
                callback(path)
            except Exception:
                LOGGER.exception("Không đánh dấu được file Output do ứng dụng ghi.")

    @staticmethod
    def _path_key(path: str | Path) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    @staticmethod
    def _copy_file_atomic(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as target_handle:
                temp_path = Path(target_handle.name)
                with source.open("rb") as source_handle:
                    shutil.copyfileobj(
                        source_handle,
                        target_handle,
                        length=1024 * 1024,
                    )
                target_handle.flush()
                os.fsync(target_handle.fileno())
            try:
                shutil.copystat(source, temp_path)
            except OSError:
                LOGGER.debug("Không sao chép được metadata file %s", source)
            os.replace(temp_path, target)
            temp_path = None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    @staticmethod
    def _mark_read_only(path: Path) -> None:
        try:
            path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        except OSError:
            LOGGER.warning("Không thể đánh dấu chỉ đọc cho %s", path)

    @staticmethod
    def _make_writable(path: Path) -> None:
        if path.exists():
            path.chmod(path.stat().st_mode | stat.S_IWUSR)


hash_file = calculate_sha256

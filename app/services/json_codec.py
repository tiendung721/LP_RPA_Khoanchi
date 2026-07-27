"""Đọc và ghi JSON đúng hợp đồng, an toàn khi ứng dụng bị ngắt giữa chừng."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from app.models import BatchDocument, DataRow
from app.schema import SchemaError, coerce_document, document_to_dict, parse_document

LOGGER = logging.getLogger(__name__)


class JsonCodecError(RuntimeError):
    """Lỗi chung đã bổ sung ngữ cảnh đường dẫn."""


class JsonReadError(JsonCodecError):
    """Không thể đọc bytes/text từ file."""


class JsonParseError(JsonCodecError):
    """Nội dung không phải JSON hợp lệ."""


class JsonSchemaError(JsonCodecError):
    """JSON hợp lệ cú pháp nhưng không ánh xạ được schema."""

    def __init__(self, message: str, schema_error: SchemaError) -> None:
        super().__init__(message)
        self.code = schema_error.code
        self.row_index = schema_error.row_index
        self.field = schema_error.field


class JsonWriteError(JsonCodecError):
    """Không thể hoàn tất ghi nguyên tử hoặc kiểm tra đọc lại."""


def backup_path_for(path: str | Path) -> Path:
    target = Path(path)
    return target.with_suffix(target.suffix + ".bak")


class JsonCodec:
    """Codec không giữ state, có thể dùng chung giữa các service/thread."""

    def loads(self, text: str | bytes | bytearray) -> BatchDocument:
        try:
            if isinstance(text, (bytes, bytearray)):
                decoded = bytes(text).decode("utf-8-sig")
            elif isinstance(text, str):
                decoded = text.removeprefix("\ufeff")
            else:
                raise TypeError("Nội dung JSON phải là str hoặc bytes.")
        except (UnicodeDecodeError, TypeError) as exc:
            raise JsonReadError("File JSON không dùng mã hóa UTF-8 hợp lệ.") from exc
        try:
            raw = json.loads(decoded, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            if isinstance(exc, json.JSONDecodeError):
                location = f" tại dòng {exc.lineno}, cột {exc.colno}"
            else:
                location = ""
            raise JsonParseError(
                f"JSON không hợp lệ{location}."
            ) from exc
        try:
            return parse_document(raw)
        except SchemaError as exc:
            raise JsonSchemaError(str(exc), exc) from exc

    def load(self, path: str | Path) -> BatchDocument:
        source = Path(path)
        try:
            payload = source.read_bytes()
        except OSError as exc:
            raise JsonReadError(f"Không thể đọc file JSON: {source}.") from exc
        return self.loads(payload)

    def load_raw(self, path: str | Path) -> object:
        """Đọc JSON nhưng chưa ánh xạ schema, hữu ích để hiển thị lỗi root."""

        source = Path(path)
        try:
            text = source.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise JsonReadError(f"Không thể đọc file JSON: {source}.") from exc
        try:
            return json.loads(text, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            if isinstance(exc, json.JSONDecodeError):
                location = f" tại dòng {exc.lineno}, cột {exc.colno}"
            else:
                location = ""
            raise JsonParseError(
                f"JSON không hợp lệ{location}."
            ) from exc

    def dumps(
        self,
        document: BatchDocument
        | dict[str, Any]
        | list[DataRow | list[Any] | tuple[Any, ...]],
    ) -> str:
        try:
            normalized = coerce_document(document)
            payload = document_to_dict(normalized)
            return json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (SchemaError, TypeError, ValueError) as exc:
            if isinstance(exc, SchemaError):
                raise JsonSchemaError(str(exc), exc) from exc
            raise JsonWriteError("Dữ liệu không thể serialize thành JSON.") from exc

    def dump_atomic(
        self,
        path: str | Path,
        document: BatchDocument
        | dict[str, Any]
        | list[DataRow | list[Any] | tuple[Any, ...]],
        *,
        create_backup: bool = True,
        validate: bool = True,
    ) -> Path:
        """Ghi temp cùng thư mục, backup bản gần nhất, replace rồi đọc đối chiếu."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            normalized = coerce_document(document)
            expected = document_to_dict(normalized)
        except SchemaError as exc:
            raise JsonSchemaError(str(exc), exc) from exc
        payload = self.dumps(normalized).encode("utf-8")
        had_previous = target.is_file()
        backup_path: Path | None = None

        try:
            if create_backup and had_previous:
                backup_path = backup_path_for(target)
                self._copy_atomic(target, backup_path)
            self._write_bytes_atomic(target, payload)
            if validate:
                actual = document_to_dict(self.load(target))
                if actual != expected:
                    raise JsonWriteError(
                        "Dữ liệu đọc lại không trùng với dữ liệu vừa lưu."
                    )
        except Exception as exc:
            try:
                if had_previous and backup_path is not None and backup_path.is_file():
                    self._copy_atomic(backup_path, target)
                elif not had_previous:
                    target.unlink(missing_ok=True)
            except OSError as rollback_error:
                raise JsonWriteError(
                    "Lưu JSON thất bại và không thể khôi phục bản trước đó."
                ) from rollback_error
            if isinstance(exc, JsonCodecError):
                raise
            raise JsonWriteError(f"Không thể lưu an toàn file JSON: {target}.") from exc
        return target

    def dump(
        self,
        document: BatchDocument
        | dict[str, Any]
        | list[DataRow | list[Any] | tuple[Any, ...]],
        path: str | Path,
        **kwargs: Any,
    ) -> Path:
        """Alias theo thứ tự tham số quen thuộc của ``json.dump``."""

        return self.dump_atomic(path, document, **kwargs)

    read = load
    write_atomic = dump_atomic
    save = dump_atomic

    @staticmethod
    def _write_bytes_atomic(target: Path, payload: bytes) -> None:
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

    @classmethod
    def _copy_atomic(cls, source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
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
                with source.open("rb") as source_handle:
                    shutil.copyfileobj(source_handle, handle, length=1024 * 1024)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                shutil.copystat(source, temp_path)
            except OSError as exc:
                # Metadata không quan trọng bằng nội dung backup.
                LOGGER.debug(
                    "Không sao chép được metadata từ %s sang backup: %s",
                    source,
                    exc,
                )
            os.replace(temp_path, target)
            temp_path = None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


def read_json(path: str | Path) -> BatchDocument:
    return JsonCodec().load(path)


def write_json_atomic(
    path: str | Path,
    document: BatchDocument
    | dict[str, Any]
    | list[DataRow | list[Any] | tuple[Any, ...]],
    *,
    create_backup: bool = True,
) -> Path:
    return JsonCodec().dump_atomic(
        path,
        document,
        create_backup=create_backup,
    )


load_json = read_json
save_json_atomic = write_json_atomic


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"Hằng số không hữu hạn không hợp lệ trong JSON: {value}")

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import AppSettings
from app.models import BatchDocument, BatchStatus, DataRow
from app.services.batch_service import BatchService, BatchValidationError
from app.services.reviewed_batch_provider import ReviewedBatchProvider


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        data_root=tmp_path / "runtime",
        inbox_dir=tmp_path / "Inbox",
        stable_seconds=0,
        stability_timeout_seconds=1,
    )


def _write_json(path: Path, rows: list[list[object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"v": 1, "d": rows}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return path


def _valid_rows() -> list[list[object]]:
    return [
        ["DRYU3026167", None, "VTN", "CV", 13_554_000],
        [None, "BL123456789", "CB", "HD", 27_500_000],
    ]


def test_receive_archives_original_and_creates_independent_working_copy(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    source = _write_json(settings.inbox_dir / "ket_qua_boc_tach.json", _valid_rows())
    original_payload = source.read_bytes()
    service = BatchService(settings)

    result = service.receive_file(source)

    assert result.created
    assert result.review is not None
    assert result.batch.original_archive_path.read_bytes() == original_payload
    assert result.batch.working_path.read_bytes() == original_payload
    assert result.batch.original_archive_path != source
    assert result.batch.working_path != source
    assert source.read_bytes() == original_payload
    assert result.batch.row_count == 2
    service.close()


def test_same_hash_does_not_create_second_batch(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = _write_json(settings.inbox_dir / "ket_qua_boc_tach.json", _valid_rows())
    second = _write_json(
        settings.inbox_dir / "ket_qua_boc_tach (1).json", _valid_rows()
    )
    service = BatchService(settings)

    created = service.receive_file(first)
    duplicate = service.receive_file(second)

    assert not duplicate.created
    assert duplicate.duplicate
    assert duplicate.batch.id == created.batch.id
    assert len(service.list_batches()) == 1
    service.close()


def test_invalid_root_is_recorded_and_copied_to_rejected(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    source = settings.inbox_dir / "ket_qua_boc_tach.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"v":1,"rows":[]}', encoding="utf-8")
    service = BatchService(settings)

    result = service.receive_file(source)

    assert result.batch.status is BatchStatus.INVALID
    assert result.batch.last_error
    assert result.batch.original_archive_path.is_file()
    assert list(settings.paths.rejected_dir.glob("*.json"))
    service.close()


def test_save_is_atomic_and_confirmation_creates_ready_snapshot(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    source = _write_json(settings.inbox_dir / "ket_qua_boc_tach.json", _valid_rows())
    service = BatchService(settings)
    received = service.receive_file(source)
    edited = BatchDocument(
        rows=[
            DataRow(None, "BL123456789", "CB", "HD", 27_500_000),
            DataRow("DRYU3026167", None, "VTN", "CV", 13_554_001),
        ]
    )

    saved = service.save_working(received.batch.id, edited)
    ready = service.confirm_batch(received.batch.id, saved.document)
    provider = ReviewedBatchProvider(service)

    assert [row.to_list() for row in saved.document.rows] == [
        row.to_list() for row in edited.rows
    ]
    assert saved.metadata.working_path.with_suffix(".json.bak").is_file()
    assert ready.metadata.status is BatchStatus.READY
    assert ready.metadata.ready_path is not None
    assert ready.metadata.ready_path.is_file()
    assert provider.get_latest_ready_json_path() == ready.metadata.ready_path
    assert provider.get_ready_json_path(received.batch.id) == ready.metadata.ready_path
    assert [item.id for item in provider.list_ready_batches()] == [received.batch.id]
    service.close()


def test_blocking_validation_prevents_confirmation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    source = _write_json(
        settings.inbox_dir / "ket_qua_boc_tach.json",
        [["DRYU3026167", None, "CB", "CV", 1]],
    )
    service = BatchService(settings)
    received = service.receive_file(source)

    with pytest.raises(BatchValidationError):
        service.confirm_batch(received.batch.id)

    assert not list(settings.paths.ready_dir.glob("*.json"))
    service.close()


def test_ready_batch_can_be_reopened_and_confirmed_to_new_snapshot(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    source = _write_json(settings.inbox_dir / "ket_qua_boc_tach.json", _valid_rows())
    service = BatchService(settings)
    received = service.receive_file(source)
    first = service.confirm_batch(received.batch.id)

    reopened = service.reopen_batch(received.batch.id)
    reopened.document.rows[0].amount = 13_554_001
    second = service.confirm_batch(received.batch.id, reopened.document)

    assert reopened.metadata.status is BatchStatus.REVIEWING
    assert first.metadata.ready_path != second.metadata.ready_path
    assert first.metadata.ready_path is not None and first.metadata.ready_path.is_file()
    assert second.metadata.ready_path is not None and second.metadata.ready_path.is_file()
    service.close()


def test_restart_restores_active_reviewing_batch(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    source = _write_json(settings.inbox_dir / "ket_qua_boc_tach.json", _valid_rows())
    first_service = BatchService(settings)
    received = first_service.receive_file(source)
    first_service.load_batch(received.batch.id)
    first_service.close()

    restarted = BatchService(settings)
    restored = restarted.restore_active_batch()

    assert restored is not None
    assert restored.metadata.id == received.batch.id
    assert restored.metadata.status is BatchStatus.REVIEWING
    restarted.close()

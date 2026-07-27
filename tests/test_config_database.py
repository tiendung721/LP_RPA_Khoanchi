from __future__ import annotations

from pathlib import Path

from app.config import AppSettings, ConfigManager
from app.database import Database
from app.models import BatchStatus
from app.repositories.batch_repository import BatchRepository


def test_first_load_creates_settings_and_runtime_directories(tmp_path: Path) -> None:
    manager = ConfigManager(tmp_path / "runtime")

    settings = manager.load()

    assert manager.settings_path.is_file()
    assert settings.data_root == tmp_path / "runtime"
    assert all(path.is_dir() for path in settings.paths.directories)


def test_settings_round_trip_utf8(tmp_path: Path) -> None:
    root = tmp_path / "Dữ liệu quyết toán"
    manager = ConfigManager(root)
    settings = AppSettings(
        data_root=root,
        gpt_url="https://chatgpt.com/g/example",
        inbox_dir=root / "Hộp nhận",
        file_pattern="ket_qua_boc_tach*.json",
    )

    manager.save(settings)
    loaded = manager.load()

    assert loaded.gpt_url == settings.gpt_url
    assert loaded.inbox_dir == settings.inbox_dir
    assert manager.settings_path.read_bytes().startswith(b"{")


def test_database_migration_and_active_batch_restore(tmp_path: Path) -> None:
    database = Database(tmp_path / "Database" / "app_state.db")
    repository = BatchRepository(database)
    working = tmp_path / "Workspace" / "1" / "ket_qua_boc_tach.json"
    working.parent.mkdir(parents=True)
    working.write_text('{"v":1,"d":[]}', encoding="utf-8")
    original = tmp_path / "Archive" / "original.json"
    original.parent.mkdir(parents=True)
    original.write_text('{"v":1,"d":[]}', encoding="utf-8")

    batch = repository.create_batch(
        source_filename="ket_qua_boc_tach.json",
        source_inbox_path=tmp_path / "Inbox" / "ket_qua_boc_tach.json",
        original_archive_path=original,
        working_path=working,
        sha256="a" * 64,
        status=BatchStatus.REVIEWING,
    )
    repository.set_active_batch_id(batch.id)

    restored = repository.restore_active_batch()

    assert restored is not None
    assert restored.id == batch.id
    assert repository.get_app_state("active_batch_id") == str(batch.id)
    database.close()

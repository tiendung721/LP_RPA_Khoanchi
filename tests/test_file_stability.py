from __future__ import annotations

from pathlib import Path

from app.services.file_stability import (
    FileStabilityChecker,
    file_sha256,
    is_temporary_file,
    wait_until_stable,
)


class FakeTime:
    def __init__(self) -> None:
        self.value = 0.0

    def clock(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def test_wait_succeeds_only_after_unchanged_signature(tmp_path: Path) -> None:
    path = tmp_path / "ket_qua_boc_tach.json"
    path.write_bytes(b"{}")
    fake = FakeTime()
    writes_remaining = 3

    def sleep_and_keep_writing(seconds: float) -> None:
        nonlocal writes_remaining
        fake.sleep(seconds)
        if writes_remaining:
            path.write_bytes(path.read_bytes() + b" ")
            writes_remaining -= 1

    checker = FileStabilityChecker(
        stable_seconds=0.3,
        timeout_seconds=2.0,
        poll_interval=0.1,
        clock=fake.clock,
        sleeper=sleep_and_keep_writing,
    )

    result = checker.wait(path)

    assert result.size == 5
    assert result.elapsed_seconds >= 0.6


def test_temporary_download_suffixes_are_ignored(tmp_path: Path) -> None:
    partial = tmp_path / "ket_qua_boc_tach.json.crdownload"
    partial.write_bytes(b"{}")

    assert is_temporary_file(partial)
    assert not wait_until_stable(
        partial,
        stable_seconds=0,
        timeout_seconds=0.1,
        poll_interval=0.01,
    )


def test_streaming_sha256_is_repeatable(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    path.write_bytes(b'{"v":1,"d":[]}')

    assert file_sha256(path) == file_sha256(path, chunk_size=3)

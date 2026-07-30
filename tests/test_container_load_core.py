from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import AppSettings
from app.container_load.service import ContainerLoadService
from app.container_load.validation import (
    ContainerResultValidationError,
    allocate_amount,
    is_container_result_document,
    load_container_result,
    normalize_container_number,
    validate_iso6346,
)


class _Launcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    def launch(self, *, bat_path, output_dir):
        self.calls.append((str(bat_path), Path(output_dir)))
        return object()


def test_iso6346_normalization_and_check_digit() -> None:
    assert normalize_container_number(" mscu-123 4566 ") == "MSCU1234566"
    assert validate_iso6346(" mscu-123 4566 ") == "MSCU1234566"

    with pytest.raises(ContainerResultValidationError) as error:
        validate_iso6346("MSCU1234567")

    assert error.value.code == "INVALID_CONTAINER_CHECK_DIGIT"


def test_result_json_is_strict_normalized_and_deduplicated(
    tmp_path: Path,
) -> None:
    path = tmp_path / "so_cont_shipping.json"
    path.write_text(
        json.dumps(
            {
                "containers": [
                    "mscu-123 4566",
                    "DRYU3026167",
                    "MSCU1234566",
                ]
            }
        ),
        encoding="utf-8",
    )

    result = load_container_result(path)

    assert is_container_result_document(path)
    assert result.source_path == path.resolve()
    assert result.containers == ("MSCU1234566", "DRYU3026167")


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ([], "INVALID_SCHEMA"),
        ({"containers": []}, "EMPTY_CONTAINERS"),
        ({"containers": ["MSCU1234566"], "extra": True}, "INVALID_SCHEMA"),
        ({"containers": [123]}, "INVALID_CONTAINER_TYPE"),
        ({"containers": ["MSCU1234567"]}, "INVALID_CONTAINER_CHECK_DIGIT"),
    ],
)
def test_result_json_rejects_invalid_schema_or_container(
    tmp_path: Path,
    payload: object,
    code: str,
) -> None:
    path = tmp_path / "so_cont_invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContainerResultValidationError) as error:
        load_container_result(path)

    assert error.value.code == code


def test_amount_allocation_preserves_exact_integer_total() -> None:
    allocations = allocate_amount(
        100,
        ("MSCU1234566", "DRYU3026167", "GAOU2112422"),
    )

    assert [item.amount for item in allocations] == [34, 33, 33]
    assert sum(item.amount or 0 for item in allocations) == 100
    assert all(
        item.amount is None
        for item in allocate_amount(
            "100",
            ("MSCU1234566", "DRYU3026167"),
        )
    )


def test_service_clears_old_result_files_and_keeps_newest(
    tmp_path: Path,
) -> None:
    output = tmp_path / "Output"
    output.mkdir()
    old_json = output / "downloaded_result.json"
    old_partial = output / "downloaded_result.json.crdownload"
    unrelated = output / "ket_qua_boc_tach.json"
    old_json.write_text(
        json.dumps({"containers": ["MSCU1234566"]}),
        encoding="utf-8",
    )
    old_partial.write_text("partial", encoding="utf-8")
    unrelated.write_text('{"v":1,"d":[]}', encoding="utf-8")
    launcher = _Launcher()
    settings = AppSettings(
        data_root=tmp_path,
        output_dir=output,
        container_gpt_bat_path=str(tmp_path / "open_container_gpt.bat"),
    )
    service = ContainerLoadService(settings, launcher)  # type: ignore[arg-type]

    assert service.clear_old_results() == 1
    assert old_partial.exists()
    assert unrelated.exists()

    older = output / "first-name.json"
    newest = output / "anything at all.json"
    older.write_text(
        json.dumps({"containers": ["DRYU3026167"]}),
        encoding="utf-8",
    )
    newest.write_text(
        json.dumps({"containers": ["GAOU2112422"]}),
        encoding="utf-8",
    )

    assert service.keep_only(newest) == 1
    assert not older.exists()
    assert newest.exists()
    assert unrelated.exists()

    service.launch_custom_gpt()
    assert launcher.calls == [
        (settings.container_gpt_bat_path, settings.output_dir)
    ]

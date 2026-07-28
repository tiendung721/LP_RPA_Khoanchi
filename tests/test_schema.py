from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models import BatchDocument, DataRow
from app.schema import SchemaError, document_to_dict, parse_document


FIXTURE = Path(__file__).parent / "fixtures" / "ket_qua_boc_tach.json"


def test_parse_valid_json_object_keeps_row_order() -> None:
    raw = {
        "v": 1,
        "d": [
            ["DRYU3026167", None, "VTN", "CV", 13_554_000],
            [None, "BL123456789", "CB", "HD", 27_500_000],
        ],
    }

    document = parse_document(raw)

    assert document.v == 1
    assert [row.to_list() for row in document.rows] == raw["d"]
    assert list(document_to_dict(document)) == ["v", "d"]


def test_parse_real_custom_assistant_fixture() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document = parse_document(raw)

    assert len(document.rows) == 47
    assert document.rows[0].fee == "VTN"
    assert document.rows[0].rule == "CV"
    assert document.rows[0].amount == 13_554_000
    assert document.rows[-1].cont == "GAOU2196608"


@pytest.mark.parametrize("raw", [[], None, "{}", 123])
def test_root_must_be_object(raw: object) -> None:
    with pytest.raises(SchemaError, match="object") as exc_info:
        parse_document(raw)
    assert exc_info.value.code == "root_not_object"


@pytest.mark.parametrize(
    "raw",
    [
        {"v": 1},
        {"d": []},
        {"v": 1, "d": [], "extra": True},
    ],
)
def test_root_must_have_exact_keys(raw: object) -> None:
    with pytest.raises(SchemaError) as exc_info:
        parse_document(raw)
    assert exc_info.value.code == "root_keys"


@pytest.mark.parametrize("version", [0, 2, True, 1.0, "1"])
def test_version_must_be_integer_one(version: object) -> None:
    with pytest.raises(SchemaError) as exc_info:
        parse_document({"v": version, "d": []})
    assert exc_info.value.code == "invalid_version"


@pytest.mark.parametrize("data", [None, {}, (), "[]"])
def test_data_must_be_array(data: object) -> None:
    with pytest.raises(SchemaError) as exc_info:
        parse_document({"v": 1, "d": data})
    assert exc_info.value.code == "data_not_array"


@pytest.mark.parametrize(
    ("row", "code"),
    [
        (None, "row_not_array"),
        (("A", None, "VTN", "CV", 1), "row_not_array"),
        (["A", None, "VTN", "CV"], "row_length"),
        (["A", None, "VTN", "CV", 1, "extra"], "row_length"),
    ],
)
def test_each_row_must_be_five_element_array(row: object, code: str) -> None:
    with pytest.raises(SchemaError) as exc_info:
        parse_document({"v": 1, "d": [row]})
    assert exc_info.value.code == code


def test_document_serializes_back_as_positional_arrays() -> None:
    document = BatchDocument(
        rows=[
            DataRow("DRYU3026167", None, "VTN", "CV", 13_554_000),
            DataRow(None, "BL123", "CB", "HD", 27_500_000),
        ]
    )
    assert document_to_dict(document) == {
        "v": 1,
        "d": [
            ["DRYU3026167", None, "VTN", "CV", 13_554_000],
            [None, "BL123", "CB", "HD", 27_500_000],
        ],
    }

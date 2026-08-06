from __future__ import annotations

import json
from pathlib import Path

from app.models import BatchDocument, DataRow
from app.services.json_codec import JsonCodec, backup_path_for


def _document() -> BatchDocument:
    return BatchDocument(
        rows=[
            DataRow("DRYU3026167", None, "VTN", "CV", 13_554_000),
            DataRow(None, "Vận đơn/01", "CB", "HD", 27_500_000),
        ]
    )


def test_read_accepts_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "ket_qua_boc_tach.json"
    path.write_bytes(
        b"\xef\xbb\xbf"
        + '{"v":1,"d":[["DRYU3026167",null,"VTN","CV",null,null,1]]}'.encode(
            "utf-8"
        )
    )

    document = JsonCodec().load(path)

    assert document.rows[0].amount == 1


def test_dump_is_minified_utf8_without_bom_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "working" / "ket_qua_boc_tach.json"
    codec = JsonCodec()

    codec.dump_atomic(path, _document())

    payload = path.read_bytes()
    assert not payload.startswith(b"\xef\xbb\xbf")
    assert b"\n" not in payload
    assert payload.decode("utf-8") == codec.dumps(_document())
    assert json.loads(payload.decode("utf-8")) == _document().to_dict()
    assert codec.load(path).to_dict() == _document().to_dict()


def test_atomic_save_keeps_source_order_and_creates_latest_backup(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ket_qua_boc_tach.json"
    codec = JsonCodec()
    first = _document()
    codec.dump_atomic(path, first)
    second = BatchDocument(rows=list(reversed(first.rows)))

    codec.dump_atomic(path, second)

    assert [row.to_list() for row in codec.load(path).rows] == [
        row.to_list() for row in second.rows
    ]
    assert codec.load(backup_path_for(path)).to_dict() == first.to_dict()

"""Repository cho lịch sử từng khoản chi được đối chiếu/ghi vào workbook BK."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.database import Database
from app.repositories.excel_run_repository import (
    _enum_text,
    _json_text,
    _json_value,
    local_now_iso,
)

POSTING_ITEM_STATUSES = frozenset(
    {
        "PLANNED",
        "POSTED",
        "ALREADY_EXISTS",
        "USER_SKIPPED",
        "NOT_MATCHED",
        "UNRESOLVED",
        "FAILED",
    }
)
SUCCESSFUL_POSTING_STATUSES = frozenset({"POSTED", "ALREADY_EXISTS"})

_UPDATABLE_COLUMNS = frozenset(
    {
        "container",
        "bl",
        "fee_original",
        "fee_selected",
        "rule",
        "amount",
        "sheet_name",
        "target_row",
        "target_column",
        "target_cell",
        "value_before",
        "value_after",
        "action",
        "status",
    }
)
_VALUE_COLUMNS = frozenset({"value_before", "value_after"})
_POSITIVE_COLUMNS = frozenset({"target_row", "target_column"})


def _posting_status(value: object) -> str:
    status = _enum_text(value, field_name="Trạng thái khoản chi")
    if status not in POSTING_ITEM_STATUSES:
        raise ValueError(f"Trạng thái khoản chi không hợp lệ: {status}.")
    return status


def _required_positive_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} phải là số nguyên dương.")
    return value


def _required_nonnegative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} phải là số nguyên không âm.")
    return value


def _optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    raw = value.value if isinstance(value, Enum) else value
    if not isinstance(raw, str):
        raise ValueError("Giá trị văn bản lịch sử khoản chi không hợp lệ.")
    return raw


@dataclass(frozen=True, slots=True)
class ExpensePostingItemRecord:
    id: int
    run_id: int
    batch_id: int
    batch_hash: str
    source_item_index: int
    container: str | None
    bl: str | None
    fee_original: str
    fee_selected: str | None
    rule: str | None
    amount: int
    sheet_name: str | None
    target_row: int | None
    target_column: int | None
    target_cell: str | None
    value_before: Any
    value_after: Any
    action: str | None
    status: str
    created_at: str

    @property
    def item_id(self) -> int:
        return self.id


class ExpensePostingRepository:
    def __init__(self, database: Database | str | Path) -> None:
        self.database = (
            database if isinstance(database, Database) else Database(database)
        )

    def create_item(
        self,
        *,
        run_id: int,
        batch_id: int,
        batch_hash: str,
        source_item_index: int,
        fee_original: object,
        amount: int,
        status: object = "PLANNED",
        container: str | None = None,
        bl: str | None = None,
        fee_selected: object | None = None,
        rule: object | None = None,
        sheet_name: str | None = None,
        target_row: int | None = None,
        target_column: int | None = None,
        target_cell: str | None = None,
        value_before: object | None = None,
        value_after: object | None = None,
        action: object | None = None,
        created_at: str | None = None,
    ) -> ExpensePostingItemRecord:
        payload = self._normalize_create_payload(
            {
                "run_id": run_id,
                "batch_id": batch_id,
                "batch_hash": batch_hash,
                "source_item_index": source_item_index,
                "container": container,
                "bl": bl,
                "fee_original": fee_original,
                "fee_selected": fee_selected,
                "rule": rule,
                "amount": amount,
                "sheet_name": sheet_name,
                "target_row": target_row,
                "target_column": target_column,
                "target_cell": target_cell,
                "value_before": value_before,
                "value_after": value_after,
                "action": action,
                "status": status,
                "created_at": created_at or local_now_iso(),
            }
        )
        with self.database.transaction(immediate=True) as connection:
            item_id = self._insert(connection, payload)
            row = connection.execute(
                "SELECT * FROM expense_posting_items WHERE id = ?",
                (item_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Không thể đọc lại lịch sử khoản chi vừa tạo.")
        return self._to_record(row)

    def create_items(
        self,
        items: Iterable[Mapping[str, Any] | object],
        *,
        run_id: int | None = None,
        batch_id: int | None = None,
        batch_hash: str | None = None,
        status: object | None = None,
    ) -> list[ExpensePostingItemRecord]:
        payloads: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, Mapping):
                payload = dict(item)
            elif is_dataclass(item) and not isinstance(item, type):
                payload = asdict(item)
            else:
                raise TypeError("Mỗi khoản chi phải là Mapping hoặc dataclass.")
            defaults = {
                "run_id": run_id,
                "batch_id": batch_id,
                "batch_hash": batch_hash,
            }
            if status is not None:
                defaults["status"] = status
            for key, value in defaults.items():
                if key not in payload and value is not None:
                    payload[key] = value
            payload.setdefault("status", "PLANNED")
            payload.setdefault("created_at", local_now_iso())
            payloads.append(self._normalize_create_payload(payload))
        if not payloads:
            return []

        ids: list[int] = []
        with self.database.transaction(immediate=True) as connection:
            for payload in payloads:
                ids.append(self._insert(connection, payload))
            placeholders = ", ".join("?" for _ in ids)
            rows = connection.execute(
                f"""
                SELECT * FROM expense_posting_items
                WHERE id IN ({placeholders})
                ORDER BY id
                """,
                ids,
            ).fetchall()
        return [self._to_record(row) for row in rows]

    save_items = create_items
    record_items = create_items

    def get_by_id(self, item_id: int) -> ExpensePostingItemRecord | None:
        row = self.database.query_one(
            "SELECT * FROM expense_posting_items WHERE id = ?",
            (item_id,),
        )
        return self._to_record(row) if row is not None else None

    def require_by_id(self, item_id: int) -> ExpensePostingItemRecord:
        record = self.get_by_id(item_id)
        if record is None:
            raise KeyError(f"Không tìm thấy lịch sử khoản chi {item_id}.")
        return record

    def update_item(
        self,
        item_id: int,
        **changes: Any,
    ) -> ExpensePostingItemRecord:
        if not changes:
            return self.require_by_id(item_id)
        unknown = set(changes).difference(_UPDATABLE_COLUMNS)
        if unknown:
            raise ValueError(
                f"Không được cập nhật các cột: {', '.join(sorted(unknown))}."
            )
        normalized: dict[str, Any] = {}
        for key, value in changes.items():
            if key == "status":
                value = _posting_status(value)
            elif key in _VALUE_COLUMNS:
                value = _json_text(value)
            elif key in _POSITIVE_COLUMNS:
                if value is not None:
                    value = _required_positive_int(value, field_name=key)
            elif key == "amount":
                value = _required_nonnegative_int(value, field_name="Số tiền")
            elif key in {
                "container",
                "bl",
                "fee_original",
                "fee_selected",
                "rule",
                "sheet_name",
                "target_cell",
                "action",
            }:
                value = _optional_text(value)
                if key == "fee_original" and not value:
                    raise ValueError("Mã phí gốc không được để trống.")
            normalized[key] = value
        assignments = ", ".join(f"{column} = ?" for column in normalized)
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                f"UPDATE expense_posting_items SET {assignments} WHERE id = ?",
                (*normalized.values(), item_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Không tìm thấy lịch sử khoản chi {item_id}.")
            row = connection.execute(
                "SELECT * FROM expense_posting_items WHERE id = ?",
                (item_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Không thể đọc lại lịch sử khoản chi vừa cập nhật.")
        return self._to_record(row)

    def list_by_run(self, run_id: int) -> list[ExpensePostingItemRecord]:
        rows = self.database.query_all(
            """
            SELECT * FROM expense_posting_items
            WHERE run_id = ?
            ORDER BY source_item_index, id
            """,
            (run_id,),
        )
        return [self._to_record(row) for row in rows]

    def list_by_batch_hash(
        self,
        batch_hash: str,
        *,
        statuses: Iterable[object] | object | None = None,
    ) -> list[ExpensePostingItemRecord]:
        parameters: list[Any] = [batch_hash]
        sql = "SELECT * FROM expense_posting_items WHERE batch_hash = ?"
        if statuses is not None:
            values = (
                [statuses]
                if isinstance(statuses, (str, Enum))
                else list(statuses)  # type: ignore[arg-type]
            )
            normalized_statuses = [_posting_status(value) for value in values]
            if not normalized_statuses:
                return []
            placeholders = ", ".join("?" for _ in normalized_statuses)
            sql += f" AND status IN ({placeholders})"
            parameters.extend(normalized_statuses)
        sql += " ORDER BY source_item_index, id"
        return [
            self._to_record(row)
            for row in self.database.query_all(sql, parameters)
        ]

    def list_successful_by_batch_hash(
        self,
        batch_hash: str,
    ) -> list[ExpensePostingItemRecord]:
        return self.list_by_batch_hash(
            batch_hash,
            statuses=SUCCESSFUL_POSTING_STATUSES,
        )

    def successful_source_indices(self, batch_hash: str) -> set[int]:
        rows = self.database.query_all(
            """
            SELECT source_item_index
            FROM expense_posting_items
            WHERE batch_hash = ?
              AND status IN ('POSTED', 'ALREADY_EXISTS')
            """,
            (batch_hash,),
        )
        return {int(row["source_item_index"]) for row in rows}

    get_successful_source_indices = successful_source_indices
    posted_source_indices = successful_source_indices

    def is_source_item_posted(
        self,
        batch_hash: str,
        source_item_index: int,
    ) -> bool:
        row = self.database.query_one(
            """
            SELECT 1
            FROM expense_posting_items
            WHERE batch_hash = ?
              AND source_item_index = ?
              AND status IN ('POSTED', 'ALREADY_EXISTS')
            LIMIT 1
            """,
            (batch_hash, source_item_index),
        )
        return row is not None

    def batch_has_successful_items(self, batch_hash: str) -> bool:
        row = self.database.query_one(
            """
            SELECT 1
            FROM expense_posting_items
            WHERE batch_hash = ?
              AND status IN ('POSTED', 'ALREADY_EXISTS')
            LIMIT 1
            """,
            (batch_hash,),
        )
        return row is not None

    has_successful_items = batch_has_successful_items

    def get_latest_successful_for_batch(
        self,
        batch_hash: str,
    ) -> ExpensePostingItemRecord | None:
        row = self.database.query_one(
            """
            SELECT item.*
            FROM expense_posting_items AS item
            JOIN excel_runs AS run ON run.id = item.run_id
            WHERE item.batch_hash = ?
              AND item.status IN ('POSTED', 'ALREADY_EXISTS')
            ORDER BY COALESCE(run.completed_at, run.started_at) DESC, item.id DESC
            LIMIT 1
            """,
            (batch_hash,),
        )
        return self._to_record(row) if row is not None else None

    @staticmethod
    def _insert(
        connection: sqlite3.Connection,
        payload: Mapping[str, Any],
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO expense_posting_items (
                run_id, batch_id, batch_hash, source_item_index, container, bl,
                fee_original, fee_selected, rule, amount, sheet_name,
                target_row, target_column, target_cell, value_before,
                value_after, action, status, created_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            tuple(
                payload[column]
                for column in (
                    "run_id",
                    "batch_id",
                    "batch_hash",
                    "source_item_index",
                    "container",
                    "bl",
                    "fee_original",
                    "fee_selected",
                    "rule",
                    "amount",
                    "sheet_name",
                    "target_row",
                    "target_column",
                    "target_cell",
                    "value_before",
                    "value_after",
                    "action",
                    "status",
                    "created_at",
                )
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _normalize_create_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
        required = {
            "run_id",
            "batch_id",
            "batch_hash",
            "source_item_index",
            "fee_original",
            "amount",
            "status",
            "created_at",
        }
        missing = required.difference(payload)
        if missing:
            raise ValueError(
                f"Thiếu trường lịch sử khoản chi: {', '.join(sorted(missing))}."
            )
        run_id = _required_positive_int(payload["run_id"], field_name="run_id")
        batch_id = _required_positive_int(
            payload["batch_id"],
            field_name="batch_id",
        )
        source_item_index = _required_nonnegative_int(
            payload["source_item_index"],
            field_name="source_item_index",
        )
        amount = _required_nonnegative_int(payload["amount"], field_name="Số tiền")
        batch_hash = _optional_text(payload["batch_hash"])
        fee_original = _optional_text(payload["fee_original"])
        created_at = _optional_text(payload["created_at"])
        if not batch_hash or not batch_hash.strip():
            raise ValueError("Hash batch không được để trống.")
        if not fee_original or not fee_original.strip():
            raise ValueError("Mã phí gốc không được để trống.")
        if not created_at:
            raise ValueError("Thời gian tạo lịch sử không được để trống.")

        target_row = payload.get("target_row")
        target_column = payload.get("target_column")
        if target_row is not None:
            target_row = _required_positive_int(target_row, field_name="target_row")
        if target_column is not None:
            target_column = _required_positive_int(
                target_column,
                field_name="target_column",
            )
        return {
            "run_id": run_id,
            "batch_id": batch_id,
            "batch_hash": batch_hash,
            "source_item_index": source_item_index,
            "container": _optional_text(payload.get("container")),
            "bl": _optional_text(payload.get("bl")),
            "fee_original": fee_original,
            "fee_selected": _optional_text(payload.get("fee_selected")),
            "rule": _optional_text(payload.get("rule")),
            "amount": amount,
            "sheet_name": _optional_text(payload.get("sheet_name")),
            "target_row": target_row,
            "target_column": target_column,
            "target_cell": _optional_text(payload.get("target_cell")),
            "value_before": _json_text(payload.get("value_before")),
            "value_after": _json_text(payload.get("value_after")),
            "action": _optional_text(payload.get("action")),
            "status": _posting_status(payload["status"]),
            "created_at": created_at,
        }

    @staticmethod
    def _to_record(row: sqlite3.Row) -> ExpensePostingItemRecord:
        return ExpensePostingItemRecord(
            id=int(row["id"]),
            run_id=int(row["run_id"]),
            batch_id=int(row["batch_id"]),
            batch_hash=str(row["batch_hash"]),
            source_item_index=int(row["source_item_index"]),
            container=row["container"],
            bl=row["bl"],
            fee_original=str(row["fee_original"]),
            fee_selected=row["fee_selected"],
            rule=row["rule"],
            amount=int(row["amount"]),
            sheet_name=row["sheet_name"],
            target_row=(
                int(row["target_row"]) if row["target_row"] is not None else None
            ),
            target_column=(
                int(row["target_column"])
                if row["target_column"] is not None
                else None
            ),
            target_cell=row["target_cell"],
            value_before=_json_value(row["value_before"]),
            value_after=_json_value(row["value_after"]),
            action=row["action"],
            status=str(row["status"]),
            created_at=str(row["created_at"]),
        )


__all__ = [
    "POSTING_ITEM_STATUSES",
    "SUCCESSFUL_POSTING_STATUSES",
    "ExpensePostingItemRecord",
    "ExpensePostingRepository",
]

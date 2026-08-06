"""Validation JSON số container và thuật toán phân bổ tiền."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.container_load.contracts import ContainerAllocation, ContainerLoadResult

_CONTAINER_RE = re.compile(r"^[A-Z]{4}[0-9]{7}$")
_ISO_LETTER_VALUES = {
    letter: value
    for letter, value in zip(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        (
            10,
            12,
            13,
            14,
            15,
            16,
            17,
            18,
            19,
            20,
            21,
            23,
            24,
            25,
            26,
            27,
            28,
            29,
            30,
            31,
            32,
            34,
            35,
            36,
            37,
            38,
        ),
        strict=True,
    )
}


class ContainerResultValidationError(ValueError):
    def __init__(self, message: str, *, code: str = "INVALID_RESULT") -> None:
        super().__init__(message)
        self.code = code


def normalize_container_number(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def iso6346_check_digit(first_ten_characters: str) -> int:
    normalized = normalize_container_number(first_ten_characters)
    if re.fullmatch(r"[A-Z]{4}[0-9]{6}", normalized) is None:
        raise ContainerResultValidationError(
            "Phần thân container phải có 4 chữ cái và 6 chữ số.",
            code="INVALID_CONTAINER_FORMAT",
        )
    total = 0
    for position, character in enumerate(normalized):
        value = (
            _ISO_LETTER_VALUES[character]
            if character.isalpha()
            else int(character)
        )
        total += value * (2**position)
    return (total % 11) % 10


def validate_iso6346(value: object) -> str:
    normalized = normalize_container_number(value)
    if _CONTAINER_RE.fullmatch(normalized) is None:
        raise ContainerResultValidationError(
            f"Container {value!r} không đúng mẫu 4 chữ cái và 7 chữ số.",
            code="INVALID_CONTAINER_FORMAT",
        )
    expected = iso6346_check_digit(normalized[:10])
    actual = int(normalized[-1])
    if actual != expected:
        raise ContainerResultValidationError(
            f"Container {normalized} sai số kiểm tra ISO 6346 "
            f"(đúng phải là {expected}).",
            code="INVALID_CONTAINER_CHECK_DIGIT",
        )
    return normalized


def row_fingerprint(row: Sequence[Any]) -> str:
    if len(row) != 7:
        raise ValueError("Dòng dùng để tạo fingerprint phải có đúng 7 giá trị.")
    payload = json.dumps(
        list(row),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_container_result(path: str | Path) -> ContainerLoadResult:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContainerResultValidationError(
            "File kết quả không phải JSON UTF-8 hợp lệ.",
            code="INVALID_JSON",
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {"containers"}:
        raise ContainerResultValidationError(
            'JSON phải có đúng root {"containers": [...]}.',
            code="INVALID_SCHEMA",
        )
    raw_containers = payload["containers"]
    if not isinstance(raw_containers, list) or not raw_containers:
        raise ContainerResultValidationError(
            "containers phải là mảng không rỗng.",
            code="EMPTY_CONTAINERS",
        )
    containers: list[str] = []
    seen: set[str] = set()
    for value in raw_containers:
        if not isinstance(value, str):
            raise ContainerResultValidationError(
                "Mỗi số container phải là chuỗi.",
                code="INVALID_CONTAINER_TYPE",
            )
        number = validate_iso6346(value)
        if number in seen:
            continue
        seen.add(number)
        containers.append(number)
    if not containers:
        raise ContainerResultValidationError(
            "Kết quả không còn container hợp lệ sau khi loại trùng.",
            code="EMPTY_CONTAINERS",
        )
    return ContainerLoadResult(source.resolve(), tuple(containers))


def is_container_result_document(path: str | Path) -> bool:
    """Nhận diện contract container bằng nội dung, không phụ thuộc tên file."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and set(payload) == {"containers"}


def allocate_amount(
    total: object,
    containers: Sequence[str],
) -> tuple[ContainerAllocation, ...]:
    normalized = tuple(str(value) for value in containers)
    if not normalized:
        raise ValueError("Cần ít nhất một container để phân bổ tiền.")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        return tuple(ContainerAllocation(container, None) for container in normalized)
    base, remainder = divmod(total, len(normalized))
    return tuple(
        ContainerAllocation(
            container,
            base + (1 if index < remainder else 0),
        )
        for index, container in enumerate(normalized)
    )


__all__ = [
    "ContainerResultValidationError",
    "allocate_amount",
    "iso6346_check_digit",
    "is_container_result_document",
    "load_container_result",
    "normalize_container_number",
    "row_fingerprint",
    "validate_iso6346",
]

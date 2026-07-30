"""Các kiểu dữ liệu cho một lượt Load số container từ JSON tải xuống."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ContainerLoadSession:
    session_id: str
    batch_id: int | None
    source_row: int
    row_runtime_id: str
    row_fingerprint: str
    requested_bl: str
    started_at_ns: int


@dataclass(frozen=True, slots=True)
class ContainerLoadResult:
    source_path: Path
    containers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContainerAllocation:
    container: str
    amount: int | None


__all__ = [
    "ContainerAllocation",
    "ContainerLoadResult",
    "ContainerLoadSession",
]

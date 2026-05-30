from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ColumnSpec:
    title: str
    key: str
    type: str
    aliases: List[str] = field(default_factory=list)


@dataclass
class RuntimeColumn:
    title: str
    key: str
    type: str
    x1: int
    x2: int


@dataclass
class RuntimeRow:
    index: int
    y1: int
    y2: int
    anchor_text: Optional[str] = None


@dataclass
class OCRText:
    text: str
    confidence: float
    box: Optional[List[Tuple[float, float]]] = None

    @property
    def center(self) -> Tuple[float, float]:
        if not self.box:
            return 0.0, 0.0
        xs = [p[0] for p in self.box]
        ys = [p[1] for p in self.box]
        return sum(xs) / len(xs), sum(ys) / len(ys)


@dataclass
class CellResult:
    row_index: int
    key: str
    title: str
    raw_text: str
    normalized_text: str
    confidence: float
    valid: bool
    error: Optional[str] = None
    crop_path: Optional[str] = None


@dataclass
class StockRecord:
    snapshot_time: str
    source_image: str
    fields: Dict[str, Any] = field(default_factory=dict)
    raw_cells: Dict[str, str] = field(default_factory=dict)
    confidence: Dict[str, float] = field(default_factory=dict)
    validation_errors: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def code(self) -> str:
        return str(self.fields.get("code") or "")

    @property
    def name(self) -> str:
        return str(self.fields.get("name") or "")

    def to_flat_dict(self, include_meta: bool = True) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        if include_meta:
            data["snapshot_time"] = self.snapshot_time
            data["source_image"] = self.source_image
        data.update(self.fields)
        data["validation_error_count"] = len(self.validation_errors)
        return data

    def to_json_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ParseResult:
    records: List[StockRecord]
    runtime_columns: List[RuntimeColumn]
    runtime_rows: List[RuntimeRow]
    warnings: List[str] = field(default_factory=list)


def safe_filename(text: str) -> str:
    keep = []
    for ch in str(text):
        if ch.isalnum() or ch in {"_", "-"}:
            keep.append(ch)
        elif ch in {" ", "."}:
            keep.append("_")
    return "".join(keep).strip("_") or "unknown"

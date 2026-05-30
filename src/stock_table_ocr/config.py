from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .models import ColumnSpec


def load_schema(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_columns(schema: Dict[str, Any]) -> List[ColumnSpec]:
    return [ColumnSpec(**item) for item in schema["columns"]]


def column_keys(schema: Dict[str, Any]) -> List[str]:
    return [item["key"] for item in schema["columns"]]

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd

from .models import StockRecord, safe_filename


def write_csv(records: List[StockRecord], path: str | Path, field_order: List[str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [r.to_flat_dict(include_meta=True) for r in records]
    columns = ["snapshot_time", "source_image"] + field_order + ["validation_error_count"]
    df = pd.DataFrame(rows)
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    df = df[columns]
    df.to_csv(path, index=False, encoding="utf-8-sig")


def write_excel(records: List[StockRecord], path: str | Path, field_order: List[str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [r.to_flat_dict(include_meta=False) for r in records]
    df = pd.DataFrame(rows)
    # Reorder to match field_order; drop any extra columns
    df = df[[c for c in field_order if c in df.columns]]
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="stocks")
        err_rows = []
        for r in records:
            for err in r.validation_errors:
                err_rows.append({"code": r.code, "name": r.name, **err})
        pd.DataFrame(err_rows).to_excel(writer, index=False, sheet_name="errors")


def write_jsonl(records: List[StockRecord], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record.to_json_dict(), ensure_ascii=False) + "\n")


def write_stock_json_files(records: List[StockRecord], output_dir: str | Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        code = record.code or f"row_{len(list(output_dir.iterdir())):03d}"
        name = record.name or "unknown"
        filename = safe_filename(f"{code}_{name}") + ".json"
        with open(output_dir / filename, "w", encoding="utf-8") as f:
            json.dump(record.to_json_dict(), f, ensure_ascii=False, indent=2)


def write_error_report(records: List[StockRecord], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for record in records:
        for err in record.validation_errors:
            rows.append({"code": record.code, "name": record.name, **err})
    if not rows:
        rows = [{"message": "no_errors"}]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=sorted(set().union(*(r.keys() for r in rows))))
        writer.writeheader()
        writer.writerows(rows)


def write_correction_log(records: List[StockRecord], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# OCR Correction Log", ""]
    count = 0
    for record in records:
        if not record.validation_errors:
            continue
        lines.append(f"## {record.code} {record.name}")
        for err in record.validation_errors:
            count += 1
            lines.append(f"- `{err.get('field', '-')}` {err.get('reason', '-')}: raw=`{err.get('raw_text', '')}` normalized=`{err.get('normalized', '')}` confidence=`{err.get('confidence', '')}`")
        lines.append("")
    if count == 0:
        lines.append("No validation errors.")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_runtime_layout(parse_result, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "columns": [c.__dict__ for c in parse_result.runtime_columns],
        "rows": [r.__dict__ for r in parse_result.runtime_rows],
        "warnings": parse_result.warnings,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

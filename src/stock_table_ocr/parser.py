from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .config import load_columns, load_schema
from .header_locator import infer_columns_from_header_ocr
from .image_utils import crop_with_padding, prepare_cell_for_ocr, read_image, write_image
from .line_detector import choose_grid_boundaries, detect_table_lines
from .models import OCRText, ParseResult, RuntimeColumn, RuntimeRow, StockRecord
from .normalizers import normalize_by_type
from .ocr_engine import BaseOCREngine
from .validators import correct_name_by_code, load_stock_dict, validate_field, validate_row_consistency


def _runtime_columns_from_grid(xs: List[int], schema_columns) -> List[RuntimeColumn]:
    cols: List[RuntimeColumn] = []
    for spec, x1, x2 in zip(schema_columns, xs[:-1], xs[1:]):
        cols.append(RuntimeColumn(spec.title, spec.key, spec.type, int(x1), int(x2)))
    return cols


def _runtime_rows_from_grid(ys: List[int]) -> List[RuntimeRow]:
    # Assume first band is header; data rows start from the second horizontal interval.
    rows: List[RuntimeRow] = []
    if len(ys) < 3:
        return rows
    for i, (y1, y2) in enumerate(zip(ys[1:-1], ys[2:])):
        if y2 - y1 >= 8:
            rows.append(RuntimeRow(index=len(rows), y1=int(y1), y2=int(y2)))
    return rows


def _infer_boundaries_from_centers(centers: List[float], image_height: int) -> List[Tuple[int, int]]:
    centers = sorted(float(c) for c in centers)
    if not centers:
        return []
    if len(centers) == 1:
        half = max(8, image_height // 80)
        return [(max(0, int(centers[0] - half)), min(image_height - 1, int(centers[0] + half)))]
    mids = [(centers[i] + centers[i + 1]) / 2 for i in range(len(centers) - 1)]
    first_gap = mids[0] - centers[0]
    last_gap = centers[-1] - mids[-1]
    boundaries = [max(0, centers[0] - first_gap)] + mids + [min(image_height - 1, centers[-1] + last_gap)]
    return [(int(boundaries[i]), int(boundaries[i + 1])) for i in range(len(boundaries) - 1)]


def _rows_from_code_anchor(
    image: np.ndarray,
    code_col: RuntimeColumn,
    ocr_engine: BaseOCREngine,
) -> Tuple[List[RuntimeRow], List[str]]:
    warnings: List[str] = []
    crop = crop_with_padding(image, code_col.x1, 0, code_col.x2, image.shape[0], padding=0)
    items = ocr_engine.recognize(crop)
    centers: List[Tuple[float, str]] = []
    for item in items:
        text = re.sub(r"\D", "", item.text.replace("O", "0").replace("o", "0"))
        if re.fullmatch(r"\d{6}", text):
            _, cy = item.center
            centers.append((cy, text))
    centers = sorted(centers)
    if not centers:
        warnings.append("代码列 OCR 未找到 6 位股票代码，无法用代码锚点推断行边界。")
        return [], warnings
    row_boxes = _infer_boundaries_from_centers([c for c, _ in centers], image.shape[0])
    rows = []
    for i, ((y1, y2), (_, code)) in enumerate(zip(row_boxes, centers)):
        rows.append(RuntimeRow(index=i, y1=y1, y2=y2, anchor_text=code))
    return rows, warnings


def _fallback_columns_by_equal_width(image_width: int, schema_columns) -> List[RuntimeColumn]:
    # Last-resort fallback: uses relative equal width only when both grid and header OCR failed.
    # This is NOT a fixed-pixel template; it adapts to the current image width but may be less accurate.
    n = len(schema_columns)
    boundaries = [int(round(i * image_width / n)) for i in range(n + 1)]
    boundaries[-1] = image_width - 1
    return _runtime_columns_from_grid(boundaries, schema_columns)


def _find_runtime_column(columns: List[RuntimeColumn], x: float) -> Optional[RuntimeColumn]:
    for col in columns:
        if col.x1 <= x <= col.x2:
            return col
    return None


def _find_runtime_row(rows: List[RuntimeRow], y: float) -> Optional[RuntimeRow]:
    for row in rows:
        if row.y1 <= y <= row.y2:
            return row
    return None


def _recognize_cells_from_page(
    image: np.ndarray,
    runtime_columns: List[RuntimeColumn],
    runtime_rows: List[RuntimeRow],
    ocr_engine: BaseOCREngine,
) -> Dict[Tuple[int, str], OCRText]:
    """Run OCR once on the full screenshot and assign text blocks to cells."""
    page_items = ocr_engine.recognize(image)
    grouped: Dict[Tuple[int, str], List[OCRText]] = {}

    for item in page_items:
        cx, cy = item.center
        row = _find_runtime_row(runtime_rows, cy)
        if row is None:
            continue
        col = _find_runtime_column(runtime_columns, cx)
        if col is None:
            continue
        grouped.setdefault((row.index, col.key), []).append(item)

    cell_results: Dict[Tuple[int, str], OCRText] = {}
    for key, items in grouped.items():
        items.sort(key=lambda item: (item.center[1], item.center[0]))
        text = "".join(item.text for item in items).strip()
        confs = [item.confidence for item in items if item.confidence is not None]
        confidence = float(sum(confs) / len(confs)) if confs else 0.0
        cell_results[key] = OCRText(text=text, confidence=confidence, box=items[0].box if items else None)

    return cell_results


def compute_runtime_layout(
    image: np.ndarray,
    schema: Dict,
    ocr_engine: Optional[BaseOCREngine] = None,
) -> Tuple[List[RuntimeColumn], List[RuntimeRow], List[str]]:
    warnings: List[str] = []
    specs = load_columns(schema)
    expected_cols = len(specs)

    line_result = detect_table_lines(image)
    xs, ys, w1 = choose_grid_boundaries(
        line_result.vertical_positions,
        line_result.horizontal_positions,
        expected_columns=expected_cols,
        image_shape=image.shape,
    )
    warnings.extend(w1)

    runtime_columns: List[RuntimeColumn] = []
    if len(xs) == expected_cols + 1:
        runtime_columns = _runtime_columns_from_grid(xs, specs)
    elif ocr_engine is not None:
        items = ocr_engine.recognize(image)
        runtime_columns, w2 = infer_columns_from_header_ocr(items, specs, image.shape[1])
        warnings.extend(w2)

    if not runtime_columns:
        warnings.append("列边界动态检测失败，已使用相对宽度兜底；建议检查表格线或表头 OCR。")
        runtime_columns = _fallback_columns_by_equal_width(image.shape[1], specs)

    runtime_rows = _runtime_rows_from_grid(ys)
    if not runtime_rows and ocr_engine is not None:
        code_col = next((c for c in runtime_columns if c.key == "code"), runtime_columns[0])
        runtime_rows, w3 = _rows_from_code_anchor(image, code_col, ocr_engine)
        warnings.extend(w3)

    if not runtime_rows:
        warnings.append("行边界动态检测失败：未检测到横线，也无法通过代码锚点推断。")

    return runtime_columns, runtime_rows, warnings


def parse_image(
    image_path: str | Path,
    schema_path: str | Path,
    ocr_engine: BaseOCREngine,
    stock_dict_path: str | Path | None = None,
    snapshot_time: Optional[str] = None,
    output_debug_cells_dir: str | Path | None = None,
    min_confidence: float = 0.85,
    binarize_cells: bool = False,
) -> ParseResult:
    image_path = Path(image_path)
    image = read_image(image_path)
    schema = load_schema(schema_path)
    specs = load_columns(schema)
    spec_by_key = {spec.key: spec for spec in specs}
    stock_dict = load_stock_dict(stock_dict_path)

    runtime_columns, runtime_rows, warnings = compute_runtime_layout(image, schema, ocr_engine=ocr_engine)
    snapshot_time = snapshot_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    debug_dir = Path(output_debug_cells_dir) if output_debug_cells_dir else None
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)

    records: List[StockRecord] = []
    for row in runtime_rows:
        fields: Dict[str, str] = {}
        raw_cells: Dict[str, str] = {}
        confidence: Dict[str, float] = {}
        errors: List[Dict] = []

        for col in runtime_columns:
            spec = spec_by_key[col.key]
            cell = crop_with_padding(image, col.x1, row.y1, col.x2, row.y2, padding=1)
            cell_for_ocr = prepare_cell_for_ocr(cell, scale=2.0, binarize=binarize_cells)

            crop_path = None
            if debug_dir:
                crop_path = debug_dir / f"row_{row.index:03d}_{col.key}.png"
                write_image(crop_path, cell_for_ocr)

            result = ocr_engine.recognize_text(cell_for_ocr)
            raw = result.text
            normalized = normalize_by_type(spec.type, raw)
            valid, reason = validate_field(spec.type, normalized)

            fields[col.key] = normalized
            raw_cells[col.key] = raw
            confidence[col.key] = result.confidence

            if result.confidence < min_confidence:
                errors.append({
                    "level": "warning",
                    "row_index": row.index,
                    "field": col.key,
                    "title": col.title,
                    "raw_text": raw,
                    "normalized": normalized,
                    "confidence": result.confidence,
                    "reason": "low_ocr_confidence",
                    "crop_path": str(crop_path) if crop_path else None,
                })
            if not valid:
                errors.append({
                    "level": "error",
                    "row_index": row.index,
                    "field": col.key,
                    "title": col.title,
                    "raw_text": raw,
                    "normalized": normalized,
                    "confidence": result.confidence,
                    "reason": reason,
                    "crop_path": str(crop_path) if crop_path else None,
                })

        errors.extend(correct_name_by_code(fields, stock_dict))
        errors.extend(validate_row_consistency(fields))

        # Filter likely blank rows if code and name are both empty.
        if not fields.get("code") and not fields.get("name"):
            continue

        records.append(StockRecord(
            snapshot_time=snapshot_time,
            source_image=str(image_path),
            fields=fields,
            raw_cells=raw_cells,
            confidence=confidence,
            validation_errors=errors,
        ))

    return ParseResult(records=records, runtime_columns=runtime_columns, runtime_rows=runtime_rows, warnings=warnings)

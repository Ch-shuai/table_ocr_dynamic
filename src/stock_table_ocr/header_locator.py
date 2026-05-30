from __future__ import annotations

import difflib
import re
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

from .models import ColumnSpec, OCRText, RuntimeColumn


def normalize_header_text(text: str) -> str:
    text = text.strip().replace(" ", "")
    text = text.replace("％", "%")
    text = text.replace("Ｔ", "T").replace("ｔ", "t")
    text = re.sub(r"[：:|丨]", "", text)
    return text


def best_header_match(text: str, columns: List[ColumnSpec], min_score: float = 0.55) -> Optional[ColumnSpec]:
    norm = normalize_header_text(text)
    best_spec: Optional[ColumnSpec] = None
    best_score = 0.0
    for spec in columns:
        aliases = [spec.title] + list(spec.aliases or [])
        for alias in aliases:
            score = difflib.SequenceMatcher(None, norm, normalize_header_text(alias)).ratio()
            if norm in normalize_header_text(alias) or normalize_header_text(alias) in norm:
                score = max(score, 0.85)
            if score > best_score:
                best_score = score
                best_spec = spec
    if best_score >= min_score:
        return best_spec
    return None


def infer_columns_from_header_ocr(
    ocr_items: List[OCRText],
    columns: List[ColumnSpec],
    image_width: int,
) -> Tuple[List[RuntimeColumn], List[str]]:
    """Infer column boundaries from OCR-detected header centers.

    This is a fallback when grid vertical line detection is not reliable. It maps
    recognized header words to the fixed schema and uses neighboring header
    centers to compute dynamic boundaries.
    """
    warnings: List[str] = []
    matches: Dict[str, Tuple[ColumnSpec, float, OCRText]] = {}

    for item in ocr_items:
        spec = best_header_match(item.text, columns)
        if not spec:
            continue
        cx, cy = item.center
        # Keep the topmost/left-most plausible detection for the same header.
        previous = matches.get(spec.key)
        if previous is None or cy < previous[1]:
            matches[spec.key] = (spec, cy, item)

    ordered: List[Tuple[ColumnSpec, float]] = []
    for spec in columns:
        if spec.key in matches:
            ordered.append((spec, matches[spec.key][2].center[0]))

    if len(ordered) < max(4, len(columns) // 3):
        warnings.append(f"表头 OCR 匹配数量不足：{len(ordered)} / {len(columns)}")
        return [], warnings

    # If only some headers are detected, interpolate missing centers by schema order.
    centers_by_idx: Dict[int, float] = {columns.index(spec): cx for spec, cx in ordered}
    all_centers: List[float] = []
    known = sorted(centers_by_idx.items())
    for i in range(len(columns)):
        if i in centers_by_idx:
            all_centers.append(centers_by_idx[i])
            continue
        left = max([(idx, cx) for idx, cx in known if idx < i], default=None)
        right = min([(idx, cx) for idx, cx in known if idx > i], default=None)
        if left and right:
            ratio = (i - left[0]) / (right[0] - left[0])
            all_centers.append(left[1] + ratio * (right[1] - left[1]))
        elif left:
            # Extend using median known gap.
            gaps = [known[j + 1][1] - known[j][1] for j in range(len(known) - 1)]
            gap = float(np.median(gaps)) if gaps else image_width / len(columns)
            all_centers.append(left[1] + (i - left[0]) * gap)
        elif right:
            gaps = [known[j + 1][1] - known[j][1] for j in range(len(known) - 1)]
            gap = float(np.median(gaps)) if gaps else image_width / len(columns)
            all_centers.append(right[1] - (right[0] - i) * gap)
        else:
            all_centers.append((i + 0.5) * image_width / len(columns))

    boundaries: List[int] = []
    boundaries.append(max(0, int(round(all_centers[0] - (all_centers[1] - all_centers[0]) / 2))))
    for i in range(len(all_centers) - 1):
        boundaries.append(int(round((all_centers[i] + all_centers[i + 1]) / 2)))
    boundaries.append(min(image_width - 1, int(round(all_centers[-1] + (all_centers[-1] - all_centers[-2]) / 2))))

    runtime_cols: List[RuntimeColumn] = []
    for spec, x1, x2 in zip(columns, boundaries[:-1], boundaries[1:]):
        runtime_cols.append(RuntimeColumn(spec.title, spec.key, spec.type, int(x1), int(x2)))

    return runtime_cols, warnings

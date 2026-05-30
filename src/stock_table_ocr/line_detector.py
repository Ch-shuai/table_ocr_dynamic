from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import cv2
import numpy as np

from .image_utils import adaptive_binary_inv


@dataclass
class LineDetectionResult:
    vertical_positions: List[int]
    horizontal_positions: List[int]
    table_bbox: Tuple[int, int, int, int]
    vertical_mask: np.ndarray
    horizontal_mask: np.ndarray


def _merge_positions(positions: List[int], max_gap: int) -> List[int]:
    if not positions:
        return []
    positions = sorted(int(p) for p in positions)
    groups = [[positions[0]]]
    for p in positions[1:]:
        if p - groups[-1][-1] <= max_gap:
            groups[-1].append(p)
        else:
            groups.append([p])
    return [int(round(sum(g) / len(g))) for g in groups]


def _line_positions_from_projection(mask: np.ndarray, axis: str, min_fraction: float, merge_gap: int) -> List[int]:
    if axis == "x":
        projection = (mask > 0).sum(axis=0)
        threshold = max(1, int(mask.shape[0] * min_fraction))
    elif axis == "y":
        projection = (mask > 0).sum(axis=1)
        threshold = max(1, int(mask.shape[1] * min_fraction))
    else:
        raise ValueError("axis must be 'x' or 'y'")
    candidates = np.where(projection >= threshold)[0].tolist()
    return _merge_positions(candidates, merge_gap)


def detect_table_lines(image: np.ndarray) -> LineDetectionResult:
    """Detect table grid lines dynamically from the current screenshot.

    This function never uses fixed template coordinates. It computes the line
    positions from the current image pixels via morphology and projection.
    """
    h, w = image.shape[:2]
    binary = adaptive_binary_inv(image, block_size=15, c=10)

    # Kernel lengths are proportional to the current image size, not hard-coded layout pixels.
    vertical_kernel_h = max(12, h // 35)
    horizontal_kernel_w = max(30, w // 35)
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, vertical_kernel_h))
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (horizontal_kernel_w, 1))

    vertical_mask = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel, iterations=1)
    horizontal_mask = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)

    vertical_positions = _line_positions_from_projection(
        vertical_mask, "x", min_fraction=0.05, merge_gap=max(2, w // 700)
    )
    horizontal_positions = _line_positions_from_projection(
        horizontal_mask, "y", min_fraction=0.12, merge_gap=max(2, h // 700)
    )

    if vertical_positions and horizontal_positions:
        x1, x2 = min(vertical_positions), max(vertical_positions)
        y1, y2 = min(horizontal_positions), max(horizontal_positions)
    else:
        x1, y1, x2, y2 = 0, 0, w - 1, h - 1

    return LineDetectionResult(
        vertical_positions=vertical_positions,
        horizontal_positions=horizontal_positions,
        table_bbox=(x1, y1, x2, y2),
        vertical_mask=vertical_mask,
        horizontal_mask=horizontal_mask,
    )


def filter_table_boundaries(positions: List[int], min_gap: int, max_value: int) -> List[int]:
    """Remove tiny duplicate/noise boundaries while preserving detected table edges."""
    merged = _merge_positions([p for p in positions if 0 <= p <= max_value], max_gap=max(2, min_gap // 5))
    if not merged:
        return []
    filtered = [merged[0]]
    for p in merged[1:]:
        if p - filtered[-1] >= min_gap:
            filtered.append(p)
    return filtered


def choose_grid_boundaries(
    vertical_positions: List[int],
    horizontal_positions: List[int],
    expected_columns: int,
    image_shape: Tuple[int, int],
) -> Tuple[List[int], List[int], List[str]]:
    """Choose dynamic boundaries from detected grid lines.

    For columns we need expected_columns+1 boundaries. If line detection returns
    extra grid/noise lines, choose the longest contiguous run with plausible gaps.
    """
    warnings: List[str] = []
    h, w = image_shape[:2]

    min_col_gap = max(12, w // 80)
    min_row_gap = max(8, h // 120)
    xs = filter_table_boundaries(vertical_positions, min_col_gap, w - 1)
    ys = filter_table_boundaries(horizontal_positions, min_row_gap, h - 1)

    needed = expected_columns + 1
    if len(xs) >= needed:
        # Select a contiguous window of needed boundaries with the largest total width.
        best = None
        best_width = -1
        for i in range(0, len(xs) - needed + 1):
            window = xs[i : i + needed]
            gaps = np.diff(window)
            # Penalize windows with very tiny gaps.
            valid_gap_count = int((gaps >= min_col_gap).sum())
            width = window[-1] - window[0] + valid_gap_count * 10000
            if width > best_width:
                best = window
                best_width = width
        xs = list(best) if best else xs[:needed]
    else:
        warnings.append(
            f"竖向表格线数量不足：检测到 {len(xs)} 条，需要 {needed} 条；将尝试 OCR 表头/比例兜底。"
        )

    if len(ys) < 3:
        warnings.append(f"横向表格线数量不足：检测到 {len(ys)} 条；将尝试代码列行锚点兜底。")

    return xs, ys, warnings

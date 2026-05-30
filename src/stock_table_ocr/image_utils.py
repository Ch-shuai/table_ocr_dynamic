from __future__ import annotations

from pathlib import Path
from typing import Tuple

import cv2
import numpy as np


def read_image(path: str | Path) -> np.ndarray:
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {path}")
    return img


def write_image(path: str | Path, image: np.ndarray) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix.lower() or ".png"
    ok, buf = cv2.imencode(ext, image)
    if not ok:
        raise RuntimeError(f"Failed to encode image to {path}")
    buf.tofile(str(path))


def adaptive_binary_inv(image: np.ndarray, block_size: int = 15, c: int = 10) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    # block size must be odd and >=3
    block_size = max(3, block_size | 1)
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block_size, c
    )


def crop_with_padding(image: np.ndarray, x1: int, y1: int, x2: int, y2: int, padding: int = 1) -> np.ndarray:
    h, w = image.shape[:2]
    xx1 = max(0, min(w, int(x1) + padding))
    yy1 = max(0, min(h, int(y1) + padding))
    xx2 = max(0, min(w, int(x2) - padding))
    yy2 = max(0, min(h, int(y2) - padding))
    if xx2 <= xx1 or yy2 <= yy1:
        return image[max(0, int(y1)):min(h, int(y2)), max(0, int(x1)):min(w, int(x2))].copy()
    return image[yy1:yy2, xx1:xx2].copy()


def prepare_cell_for_ocr(cell: np.ndarray, scale: float = 2.0, binarize: bool = False) -> np.ndarray:
    if scale and scale != 1.0:
        cell = cv2.resize(cell, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if not binarize:
        return cell
    gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY) if cell.ndim == 3 else cell
    # For small colored numbers, overly aggressive binarization may hurt. Keep optional.
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, 8)

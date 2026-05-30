import cv2
import numpy as np

from stock_table_ocr.line_detector import choose_grid_boundaries, detect_table_lines


def make_table(cols=5, rows=4, cell_w=80, cell_h=30):
    img = np.ones((rows * cell_h + 1, cols * cell_w + 1, 3), dtype=np.uint8) * 255
    for c in range(cols + 1):
        x = c * cell_w
        cv2.line(img, (x, 0), (x, img.shape[0] - 1), (0, 0, 0), 1)
    for r in range(rows + 1):
        y = r * cell_h
        cv2.line(img, (0, y), (img.shape[1] - 1, y), (0, 0, 0), 1)
    return img


def test_detect_lines_on_synthetic_table():
    img = make_table(cols=5, rows=4)
    result = detect_table_lines(img)
    xs, ys, warnings = choose_grid_boundaries(result.vertical_positions, result.horizontal_positions, 5, img.shape)
    assert len(xs) == 6
    assert len(ys) >= 5
    assert xs[0] <= 2
    assert xs[-1] >= img.shape[1] - 3

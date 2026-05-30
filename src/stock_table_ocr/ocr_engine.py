from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np

from .models import OCRText


class BaseOCREngine:
    def recognize(self, image: np.ndarray) -> List[OCRText]:
        raise NotImplementedError

    def recognize_text(self, image: np.ndarray) -> OCRText:
        items = self.recognize(image)
        if not items:
            return OCRText(text="", confidence=0.0, box=None)
        text = "".join(item.text for item in items).strip()
        confs = [item.confidence for item in items if item.confidence is not None]
        avg = float(sum(confs) / len(confs)) if confs else 0.0
        return OCRText(text=text, confidence=avg, box=items[0].box)


class NullOCREngine(BaseOCREngine):
    """A no-op OCR engine used for detector/debug tests when PaddleOCR is unavailable."""

    def recognize(self, image: np.ndarray) -> List[OCRText]:
        return []


class PaddleOCREngine(BaseOCREngine):
    """Thin wrapper around PaddleOCR.

    PaddleOCR has had several return formats across versions. This wrapper tries
    to parse the common v2-style output: [ [box, (text, score)], ... ].
    """

    def __init__(self, lang: str = "ch", use_angle_cls: bool = False, **kwargs):
        try:
            from paddleocr import PaddleOCR
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError(
                "PaddleOCR is not installed or cannot be imported. Install with: pip install -r requirements.txt"
            ) from exc
        self.engine = PaddleOCR(lang=lang, use_angle_cls=use_angle_cls, **kwargs)

    def recognize(self, image: np.ndarray) -> List[OCRText]:  # pragma: no cover - depends on optional package/model
        # PaddleOCR 3.6.0+ (PaddleX pipeline) enables doc orientation classify
        # and unwarping by default, which destroys small cell images. Disable them.
        result = self.engine.ocr(
            image,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        return parse_paddle_result(result)


def parse_paddle_result(result) -> List[OCRText]:
    items: List[OCRText] = []
    if not result:
        return items

    # PaddleOCR v3+ (e.g. 3.6.0) format: list of dicts with rec_texts / rec_scores / rec_boxes
    if isinstance(result, list) and result and isinstance(result[0], dict):
        page = result[0]
        texts = page.get("rec_texts") or []
        scores = page.get("rec_scores") or []
        boxes = page.get("rec_polys") if page.get("rec_polys") is not None else page.get("rec_boxes") if page.get("rec_boxes") is not None else []
        for text, score, box in zip(texts, scores, boxes):
            try:
                parsed_box = _to_box_list(box)
                items.append(OCRText(text=str(text), confidence=float(score), box=parsed_box))
            except Exception:
                continue
        return items

    # v2 common format: result = [[ [box, (text, score)], ... ]]
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], list):
        candidates = result[0]
    else:
        candidates = result

    for line in candidates or []:
        try:
            box = line[0]
            rec = line[1]
            text = str(rec[0])
            score = float(rec[1])
            parsed_box = [(float(x), float(y)) for x, y in box]
            items.append(OCRText(text=text, confidence=score, box=parsed_box))
        except Exception:
            continue
    return items


def _to_box_list(box) -> Optional[List[Tuple[float, float]]]:
    """Convert various box formats to list of (x, y) tuples."""
    if box is None:
        return None
    arr = np.asarray(box)
    if arr.ndim == 1 and arr.shape[0] == 4:
        # [x1, y1, x2, y2] -> [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
        x1, y1, x2, y2 = float(arr[0]), float(arr[1]), float(arr[2]), float(arr[3])
        return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    if arr.ndim == 2:
        return [(float(x), float(y)) for x, y in arr]
    return None


def build_ocr_engine(name: str = "paddle", **kwargs) -> BaseOCREngine:
    if name == "paddle":
        return PaddleOCREngine(**kwargs)
    if name in {"null", "none", "debug"}:
        return NullOCREngine()
    raise ValueError(f"Unsupported OCR engine: {name}")

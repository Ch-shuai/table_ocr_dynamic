import pytest

from stock_table_ocr.ocr_engine import parse_paddle_result
from stock_table_ocr.parser import _recognize_cells_from_page
from stock_table_ocr.models import OCRText, RuntimeColumn, RuntimeRow


def test_parse_paddle_result_v2_style():
    result = [[
        [[[0,0],[10,0],[10,10],[0,10]], ("代码", 0.99)],
        [[[20,0],[40,0],[40,10],[20,10]], ("名称", 0.98)],
    ]]
    items = parse_paddle_result(result)
    assert [i.text for i in items] == ["代码", "名称"]
    assert items[0].confidence == 0.99


class FakePageOCREngine:
    def __init__(self):
        self.calls = 0

    def recognize(self, image):
        self.calls += 1
        return [
            OCRText("600", 0.9, [(1, 1), (9, 1), (9, 9), (1, 9)]),
            OCRText("105", 0.8, [(11, 1), (19, 1), (19, 9), (11, 9)]),
            OCRText("永鼎股份", 0.95, [(31, 1), (59, 1), (59, 9), (31, 9)]),
            OCRText("表头", 0.99, [(31, -20), (59, -20), (59, -10), (31, -10)]),
        ]


def test_recognize_cells_from_page_groups_full_image_ocr_once():
    engine = FakePageOCREngine()
    columns = [
        RuntimeColumn("代码", "code", "code", 0, 25),
        RuntimeColumn("名称", "name", "name", 25, 70),
    ]
    rows = [RuntimeRow(index=0, y1=0, y2=20)]

    cells = _recognize_cells_from_page(None, columns, rows, engine)

    assert engine.calls == 1
    assert cells[(0, "code")].text == "600105"
    assert cells[(0, "code")].confidence == pytest.approx(0.85)
    assert cells[(0, "name")].text == "永鼎股份"

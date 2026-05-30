from stock_table_ocr.ocr_engine import parse_paddle_result


def test_parse_paddle_result_v2_style():
    result = [[
        [[[0,0],[10,0],[10,10],[0,10]], ("代码", 0.99)],
        [[[20,0],[40,0],[40,10],[20,10]], ("名称", 0.98)],
    ]]
    items = parse_paddle_result(result)
    assert [i.text for i in items] == ["代码", "名称"]
    assert items[0].confidence == 0.99

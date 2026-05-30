from stock_table_ocr.normalizers import normalize_code, normalize_percent, normalize_unit_number
from stock_table_ocr.validators import validate_field


def test_normalize_code_common_ocr_errors():
    assert normalize_code("6OO105") == "600105"
    assert normalize_code("００２１３０") == "002130"


def test_percent_normalization_and_validation():
    assert normalize_percent("-1.48") == "-1.48%"
    assert validate_field("percent", "-1.48%")[0]
    assert not validate_field("percent_range", "199.01%")[0]


def test_unit_number_keeps_units_and_arrow():
    assert normalize_unit_number("36k↓") == "36K↓"
    assert normalize_unit_number("2.41億") == "2.41亿"

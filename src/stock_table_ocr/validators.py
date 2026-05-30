from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple


def load_stock_dict(path: str | Path | None) -> Dict[str, Dict[str, str]]:
    if not path:
        return {}
    path = Path(path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        result: Dict[str, Dict[str, str]] = {}
        for row in reader:
            code = (row.get("code") or row.get("代码") or "").strip()
            name = (row.get("name") or row.get("名称") or "").strip()
            if re.fullmatch(r"\d{6}", code):
                result[code] = {"name": name, **row}
        return result


def validate_field(field_type: str, value: str) -> Tuple[bool, str | None]:
    value = value or ""
    if field_type == "stock_code":
        if re.fullmatch(r"\d{6}", value):
            return True, None
        return False, "stock_code_must_be_6_digits"

    if field_type == "stock_name":
        return (bool(value), None if value else "stock_name_empty")

    if field_type == "percent":
        if value == "--" or re.fullmatch(r"[+-]?\d+(?:\.\d+)?%", value):
            return True, None
        return False, "percent_format_invalid"

    if field_type == "percent_non_negative":
        if value == "--":
            return True, None
        if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?%", value):
            return False, "percent_format_invalid"
        try:
            if float(value.replace("%", "")) < 0:
                return False, "percent_should_not_be_negative"
        except ValueError:
            return False, "percent_parse_failed"
        return True, None

    if field_type == "percent_range":
        if value == "--":
            return True, None
        if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?%", value):
            return False, "percent_format_invalid"
        try:
            num = float(value.replace("%", ""))
        except ValueError:
            return False, "percent_parse_failed"
        if -100 <= num <= 100:
            return True, None
        return False, "percent_out_of_-100_to_100_range"

    if field_type in {"number", "number_or_empty"}:
        if value == "--" or value == "":
            return True, None
        if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
            return True, None
        return False, "number_format_invalid"

    if field_type == "number_non_negative":
        if value == "--" or value == "":
            return True, None
        if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
            return False, "number_format_invalid"
        try:
            if float(value) < 0:
                return False, "number_should_not_be_negative"
        except ValueError:
            return False, "number_parse_failed"
        return True, None

    if field_type in {"unit_number", "unit_number_with_arrow"}:
        if value == "--" or value == "":
            return True, None
        if re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:万|亿|K|M)?[↑↓]?", value):
            return True, None
        return False, "unit_number_format_invalid"

    return True, None


def correct_name_by_code(fields: Dict[str, str], stock_dict: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
    errors: List[Dict[str, str]] = []
    code = fields.get("code", "")
    if code in stock_dict:
        expected = stock_dict[code].get("name", "")
        old = fields.get("name", "")
        if expected and old != expected:
            fields["name"] = expected
            errors.append({
                "level": "info",
                "field": "name",
                "reason": "name_corrected_by_stock_code_dict",
                "old": old,
                "new": expected,
            })
    return errors


def validate_row_consistency(fields: Dict[str, str]) -> List[Dict[str, str]]:
    errors: List[Dict[str, str]] = []
    code = fields.get("code", "")
    if not re.fullmatch(r"\d{6}", code or ""):
        errors.append({"level": "error", "field": "code", "reason": "row_anchor_code_missing_or_invalid"})

    # Direction check: change_pct and change_amount should usually have the same sign.
    pct = (fields.get("change_pct") or "").replace("%", "")
    amount = fields.get("change_amount") or ""
    try:
        pct_num = float(pct)
        amount_num = float(amount)
        if pct_num > 0 and amount_num < 0:
            errors.append({"level": "warning", "field": "change_amount", "reason": "change_direction_conflict"})
        if pct_num < 0 and amount_num > 0:
            errors.append({"level": "warning", "field": "change_amount", "reason": "change_direction_conflict"})
    except Exception:
        pass

    required = ["code", "name", "change_pct", "price"]
    for key in required:
        if not fields.get(key):
            errors.append({"level": "error", "field": key, "reason": "required_field_empty"})
    return errors

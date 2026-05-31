from __future__ import annotations

import re
from typing import Optional

FULLWIDTH_MAP = str.maketrans({
    "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
    "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
    "．": ".", "－": "-", "—": "-", "–": "-", "％": "%",
    "，": ",", "＋": "+", "：": ":",
})


def clean_common(text: str | None) -> str:
    if text is None:
        return ""
    text = str(text).strip().translate(FULLWIDTH_MAP)
    text = text.replace(" ", "").replace("\n", "")
    text = text.replace("億", "亿").replace("萬", "万")
    text = text.replace("﹣", "-").replace("﹢", "+")
    return text


def normalize_code(text: str | None) -> str:
    text = clean_common(text)
    text = text.replace("O", "0").replace("o", "0")
    text = text.replace("I", "1").replace("l", "1").replace("|", "1")
    # Keep letters and digits (supports codes like AU9999, sh000001)
    return re.sub(r"[^A-Za-z0-9]", "", text)


def normalize_percent(text: str | None, add_symbol: bool = True) -> str:
    text = clean_common(text)
    if text in {"", "--", "-"}:
        return "--" if text in {"--", "-"} else ""
    text = text.replace("O", "0").replace("o", "0")
    # Keep only leading sign, digits, dot and percent.
    match = re.search(r"[+-]?\d+(?:\.\d+)?", text)
    if not match:
        return text
    value = match.group(0)
    if add_symbol:
        value += "%"
    return value


def normalize_number(text: str | None) -> str:
    text = clean_common(text)
    if text in {"", "--"}:
        return text
    text = text.replace("O", "0").replace("o", "0")
    match = re.search(r"[+-]?\d+(?:\.\d+)?", text)
    return match.group(0) if match else text


def normalize_unit_number(text: str | None) -> str:
    text = clean_common(text)
    if text in {"", "--"}:
        return text
    text = text.replace("O", "0").replace("o", "0")
    # OCR sometimes misrecognises ↑ as Chinese character "个" (especially for green/red arrows).
    text = text.replace("个", "↑")
    # Preserve financial units and arrows. "万亿" must come before "万" to avoid partial match.
    allowed = re.findall(r"[+-]?\d+(?:\.\d+)?(?:万亿|万|亿|K|k|M|m)?[↑↓]?", text)
    if allowed:
        out = allowed[0].replace("k", "K").replace("m", "M")
        return out
    return text


def normalize_text(text: str | None) -> str:
    return clean_common(text)


def normalize_by_type(field_type: str, text: str | None) -> str:
    if field_type == "stock_code":
        return normalize_code(text)
    if field_type in {"percent", "percent_non_negative", "percent_range"}:
        return normalize_percent(text)
    if field_type in {"number", "number_or_empty", "number_non_negative"}:
        return normalize_number(text)
    if field_type in {"unit_number", "unit_number_with_arrow"}:
        return normalize_unit_number(text)
    return normalize_text(text)

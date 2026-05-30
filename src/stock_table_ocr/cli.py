from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from .config import column_keys, load_schema
from .ocr_engine import build_ocr_engine
from .outputs import (
    write_correction_log,
    write_csv,
    write_error_report,
    write_excel,
    write_jsonl,
    write_runtime_layout,
    write_stock_json_files,
)
from .parser import compute_runtime_layout, parse_image
from .image_utils import read_image


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Dynamic structured OCR parser for stock market table screenshots.")
    p.add_argument("--image", required=True, help="Input PNG/JPG screenshot path.")
    p.add_argument("--schema", default="configs/stock_table_schema.json", help="Schema JSON path.")
    p.add_argument("--stock-dict", default="data/stock_code_name_sample.csv", help="Stock code-name CSV path.")
    p.add_argument("--out", default="output", help="Output directory.")
    p.add_argument("--snapshot-time", default=None, help="Snapshot time, e.g. '2026-05-29 10:30:00'.")
    p.add_argument("--ocr", default="paddle", choices=["paddle", "null", "debug"], help="OCR engine.")
    p.add_argument("--min-confidence", type=float, default=0.85, help="Low-confidence threshold.")
    p.add_argument("--debug-cells", action="store_true", help="Save every cropped cell for manual inspection.")
    p.add_argument("--binarize-cells", action="store_true", help="Apply adaptive binary threshold to each cell before OCR.")
    p.add_argument("--detect-only", action="store_true", help="Only compute dynamic runtime layout, no OCR parsing.")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    schema = load_schema(args.schema)

    if args.detect_only:
        image = read_image(args.image)
        ocr_engine = None if args.ocr in {"null", "debug"} else build_ocr_engine(args.ocr, lang="ch", use_angle_cls=False)
        columns, rows, warnings = compute_runtime_layout(image, schema, ocr_engine=ocr_engine)
        runtime_result = type("RuntimeLayoutOnly", (), {})()
        runtime_result.runtime_columns = columns
        runtime_result.runtime_rows = rows
        runtime_result.warnings = warnings
        write_runtime_layout(runtime_result, out_dir / "runtime_layout.json")
        print(f"Detected columns={len(columns)}, rows={len(rows)}. Layout saved to {out_dir / 'runtime_layout.json'}")
        if warnings:
            print("Warnings:")
            for w in warnings:
                print(f"- {w}")
        return 0

    ocr_engine = build_ocr_engine(args.ocr, lang="ch", use_angle_cls=False) if args.ocr == "paddle" else build_ocr_engine(args.ocr)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    debug_dir = out_dir / "debug_cells" / stamp if args.debug_cells else None

    result = parse_image(
        image_path=args.image,
        schema_path=args.schema,
        ocr_engine=ocr_engine,
        stock_dict_path=args.stock_dict,
        snapshot_time=args.snapshot_time,
        output_debug_cells_dir=debug_dir,
        min_confidence=args.min_confidence,
        binarize_cells=args.binarize_cells,
    )

    field_order = column_keys(schema)
    write_csv(result.records, out_dir / f"market_table_{stamp}.csv", field_order)
    write_excel(result.records, out_dir / f"market_table_{stamp}.xlsx", field_order)
    write_jsonl(result.records, out_dir / f"market_table_{stamp}.jsonl")
    write_stock_json_files(result.records, out_dir / "stocks")
    write_error_report(result.records, out_dir / "review" / f"ocr_error_cells_{stamp}.csv")
    write_correction_log(result.records, out_dir / "review" / f"correction_log_{stamp}.md")
    write_runtime_layout(result, out_dir / f"runtime_layout_{stamp}.json")

    print(f"Parsed {len(result.records)} stock rows.")
    print(f"Output directory: {out_dir.resolve()}")
    if result.warnings:
        print("Warnings:")
        for w in result.warnings:
            print(f"- {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

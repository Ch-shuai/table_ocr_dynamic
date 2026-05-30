from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, send_from_directory

# Ensure src/ is on path for imports
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from stock_table_ocr.parser import compute_runtime_layout, parse_image
from stock_table_ocr.config import load_schema, column_keys
from stock_table_ocr.ocr_engine import build_ocr_engine
from stock_table_ocr.image_utils import read_image
from stock_table_ocr.outputs import (
    write_csv,
    write_excel,
    write_jsonl,
    write_stock_json_files,
    write_error_report,
    write_correction_log,
    write_runtime_layout,
)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


@app.template_filter("tojson_pretty")
def tojson_pretty(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/parse", methods=["POST"])
def parse():
    start_time = time.time()
    file = request.files.get("image")
    if not file or file.filename == "":
        return "未选择图片", 400

    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    run_upload_dir = UPLOAD_DIR / run_id
    run_upload_dir.mkdir(parents=True, exist_ok=True)
    image_path = run_upload_dir / "input.png"
    file.save(image_path)

    schema_path = BASE_DIR / "configs" / "stock_table_schema.json"
    stock_dict_path = BASE_DIR / "data" / "stock_code_name_sample.csv"
    output_dir = BASE_DIR / "output" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    snapshot_time = request.form.get("snapshot_time") or None
    min_confidence = float(request.form.get("min_confidence", "0.85"))
    binarize_cells = bool(request.form.get("binarize_cells"))
    detect_only = bool(request.form.get("detect_only"))
    debug_cells = bool(request.form.get("debug_cells"))

    if detect_only:
        image = read_image(str(image_path))
        schema = load_schema(str(schema_path))
        columns, rows, warnings = compute_runtime_layout(image, schema, ocr_engine=None)
        elapsed = round(time.time() - start_time, 2)
        (output_dir / ".elapsed").write_text(str(elapsed))
        # Convert dataclasses to dicts for template
        layout_data = {
            "columns": [{"title": c.title, "key": c.key, "type": c.type, "x1": c.x1, "x2": c.x2} for c in columns],
            "rows": [{"index": r.index, "y1": r.y1, "y2": r.y2, "anchor_text": r.anchor_text} for r in rows],
            "warnings": warnings,
        }
        return render_template(
            "index.html",
            has_result=True,
            detect_only=True,
            run_id=run_id,
            layout_data=layout_data,
        )

    ocr_engine = build_ocr_engine("paddle", lang="ch")
    debug_dir = output_dir / "debug_cells" if debug_cells else None

    result = parse_image(
        image_path=str(image_path),
        schema_path=str(schema_path),
        ocr_engine=ocr_engine,
        stock_dict_path=str(stock_dict_path),
        snapshot_time=snapshot_time,
        output_debug_cells_dir=debug_dir,
        min_confidence=min_confidence,
        binarize_cells=binarize_cells,
    )

    elapsed = round(time.time() - start_time, 2)
    (output_dir / ".elapsed").write_text(str(elapsed))

    # Save outputs
    field_order = column_keys(load_schema(str(schema_path)))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    write_csv(result.records, output_dir / f"market_table_{stamp}.csv", field_order)
    write_excel(result.records, output_dir / f"market_table_{stamp}.xlsx", field_order)
    write_jsonl(result.records, output_dir / f"market_table_{stamp}.jsonl")
    write_stock_json_files(result.records, output_dir / "stocks")
    write_error_report(result.records, output_dir / "review" / f"ocr_error_cells_{stamp}.csv")
    write_correction_log(result.records, output_dir / "review" / f"correction_log_{stamp}.md")
    write_runtime_layout(result, output_dir / f"runtime_layout_{stamp}.json")

    return redirect(url_for("result", run_id=run_id))


@app.route("/result/<run_id>")
def result(run_id):
    output_dir = BASE_DIR / "output" / run_id
    if not output_dir.exists():
        return "结果不存在", 404

    # Find output files by pattern
    csv_files = list(output_dir.glob("market_table_*.csv"))
    jsonl_files = list(output_dir.glob("market_table_*.jsonl"))
    layout_files = list(output_dir.glob("runtime_layout_*.json"))
    error_files = list(output_dir.glob("review/ocr_error_cells_*.csv"))
    log_files = list(output_dir.glob("review/correction_log_*.md"))

    # Load CSV data
    csv_data = []
    csv_headers = []
    if csv_files:
        with open(csv_files[0], "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            csv_headers = reader.fieldnames or []
            csv_data = list(reader)

    # Load JSONL data
    jsonl_data = []
    if jsonl_files:
        with open(jsonl_files[0], "r", encoding="utf-8") as f:
            jsonl_data = [json.loads(line) for line in f if line.strip()]

    # Load layout data
    layout_data = {}
    if layout_files:
        with open(layout_files[0], "r", encoding="utf-8") as f:
            layout_data = json.load(f)

    # Load error report
    error_data = []
    if error_files:
        with open(error_files[0], "r", encoding="utf-8-sig") as f:
            error_data = list(csv.DictReader(f))

    # Load correction log
    log_content = ""
    if log_files:
        with open(log_files[0], "r", encoding="utf-8") as f:
            log_content = f.read()

    # Load stock JSON files
    stock_files = []
    stocks_dir = output_dir / "stocks"
    if stocks_dir.exists():
        stock_files = sorted([p.name for p in stocks_dir.glob("*.json")])

    # Load debug cell images
    debug_cells = []
    debug_dir = output_dir / "debug_cells"
    if debug_dir.exists():
        subdirs = sorted([d for d in debug_dir.iterdir() if d.is_dir()])
        for subdir in subdirs:
            images = sorted([p.name for p in subdir.glob("*.png")])
            if images:
                debug_cells.append({"subdir": subdir.name, "images": images})

    # Load elapsed time
    elapsed_time = None
    elapsed_file = output_dir / ".elapsed"
    if elapsed_file.exists():
        try:
            elapsed_time = float(elapsed_file.read_text().strip())
        except ValueError:
            elapsed_time = None

    # Calculate recognition rate stats
    stats = _calc_stats(jsonl_data)

    return render_template(
        "index.html",
        has_result=True,
        run_id=run_id,
        csv_headers=csv_headers,
        csv_data=csv_data,
        jsonl_data=jsonl_data,
        layout_data=layout_data,
        error_data=error_data,
        log_content=log_content,
        stock_files=stock_files,
        debug_cells=debug_cells,
        stats=stats,
        elapsed_time=elapsed_time,
    )


def _calc_stats(jsonl_data):
    """Calculate recognition rate statistics from parsed records."""
    if not jsonl_data:
        return {}

    total_records = len(jsonl_data)
    field_keys = list(jsonl_data[0]["fields"].keys()) if jsonl_data else []
    total_cells = total_records * len(field_keys)

    field_stats = {}
    for key in field_keys:
        high_conf = 0
        low_conf = 0
        empty_raw = 0
        for r in jsonl_data:
            conf = r["confidence"].get(key, 0.0)
            raw = r["raw_cells"].get(key, "")
            if raw == "" or raw is None:
                empty_raw += 1
            elif conf >= 0.85:
                high_conf += 1
            else:
                low_conf += 1
        total = total_records
        rate = round((high_conf + empty_raw) / total * 100, 1) if total else 0
        field_stats[key] = {
            "high_conf": high_conf,
            "low_conf": low_conf,
            "empty": empty_raw,
            "rate": rate,
        }

    overall_high = sum(s["high_conf"] for s in field_stats.values())
    overall_empty = sum(s["empty"] for s in field_stats.values())
    overall_low = sum(s["low_conf"] for s in field_stats.values())
    overall_rate = round((overall_high + overall_empty) / total_cells * 100, 1) if total_cells else 0

    return {
        "total_records": total_records,
        "total_fields": len(field_keys),
        "total_cells": total_cells,
        "high_conf": overall_high,
        "low_conf": overall_low,
        "empty": overall_empty,
        "overall_rate": overall_rate,
        "field_stats": field_stats,
    }


@app.route("/cell_image/<run_id>/<subdir>/<filename>")
def cell_image(run_id, subdir, filename):
    return send_from_directory(
        BASE_DIR / "output" / run_id / "debug_cells" / subdir,
        filename,
    )


@app.route("/original_image/<run_id>")
def original_image(run_id):
    return send_from_directory(UPLOAD_DIR / run_id, "input.png")


@app.route("/stock_json/<run_id>/<filename>")
def stock_json(run_id, filename):
    return send_from_directory(BASE_DIR / "output" / run_id / "stocks", filename)


if __name__ == "__main__":
    app.run(debug=True, port=5000)

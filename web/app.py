from __future__ import annotations

import csv
import json
import os
import re
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify

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

_OCR_ENGINE = None
_OCR_ENGINE_INIT_LOCK = threading.Lock()
_OCR_RECOGNITION_LOCK = threading.Lock()

_RECOGNITION_TASKS: Dict[str, Dict[str, Any]] = {}
_TASKS_LOCK = threading.Lock()


def _upsert_task(batch_id: str, **kwargs) -> None:
    """Thread-safe task status update."""
    with _TASKS_LOCK:
        if batch_id not in _RECOGNITION_TASKS:
            _RECOGNITION_TASKS[batch_id] = {"batch_id": batch_id}
        _RECOGNITION_TASKS[batch_id].update(kwargs)


def _get_tasks(limit: int = 50) -> List[Dict[str, Any]]:
    """Return latest tasks ordered by created_at desc."""
    with _TASKS_LOCK:
        tasks = list(_RECOGNITION_TASKS.values())
    tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return tasks[:limit]


def get_ocr_engine():
    """Create one PaddleOCR engine per web process and reuse it across requests."""
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        with _OCR_ENGINE_INIT_LOCK:
            if _OCR_ENGINE is None:
                _OCR_ENGINE = build_ocr_engine("paddle", lang="ch")
    return _OCR_ENGINE


@app.template_filter("tojson_pretty")
def tojson_pretty(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


@app.route("/")
def index():
    return render_template("index.html", tasks=_get_tasks())


@app.route("/tasks")
def tasks():
    return jsonify({"tasks": _get_tasks()})


@app.route("/parse", methods=["POST"])
def parse():
    start_time = time.time()
    file = request.files.get("image")
    if not file or file.filename == "":
        return "未选择图片", 400

    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
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

    ocr_engine = get_ocr_engine()
    debug_dir = output_dir / "debug_cells" if debug_cells else None

    # PaddleOCR predictors are heavy and not guaranteed to be thread-safe.
    # Serializing recognition keeps long-running web sessions stable under load.
    with _OCR_RECOGNITION_LOCK:
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


@app.route("/download_excel/<run_id>")
def download_excel(run_id):
    output_dir = BASE_DIR / "output" / run_id
    if not output_dir.exists():
        return "结果不存在", 404
    excel_files = list(output_dir.glob("market_table_*.xlsx"))
    if not excel_files:
        return "Excel 文件不存在", 404
    return send_from_directory(
        output_dir,
        excel_files[0].name,
        as_attachment=True,
        download_name=f"stock_table_{run_id}.xlsx",
    )


# ── External API for MoneyMoneyHome integration ──


SCHEMA_PATH = BASE_DIR / "configs" / "stock_table_schema.json"
STOCK_DICT_PATH = BASE_DIR / "data" / "stock_code_name_sample.csv"


def _parse_unit_number_to_float(val: str) -> float | None:
    """Convert unit_number string like '+1.23亿' or '-456.78万' to float (in 亿)."""
    if val is None or val == "" or val == "-":
        return None
    text = str(val).strip()
    # Extract numeric part and unit
    m = re.search(r"[+-]?\d+(?:\.\d+)?", text)
    if not m:
        return None
    num = float(m.group())
    if "亿" in text:
        return num
    elif "万" in text:
        return round(num / 10000, 4)
    elif "K" in text.upper():
        return round(num * 0.0001, 4)
    elif "M" in text.upper():
        return round(num * 0.01, 4)
    else:
        return num


def _parse_percent(val: str) -> float | None:
    """Convert percent string like '+1.23%' or '-0.56' to float."""
    if val is None or val == "" or val == "-":
        return None
    text = str(val).replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _parse_number(val: str) -> float | None:
    """Convert number string to float."""
    if val is None or val == "" or val == "-":
        return None
    text = str(val).strip()
    try:
        return float(text)
    except ValueError:
        return None


def _convert_record_to_snapshot(record, row_index: int) -> dict:
    """Convert a StockRecord to the snapshot format expected by MoneyMoneyHome."""
    fields = record.fields
    raw = record.raw_cells
    confidence = record.confidence

    avg_conf = 0.0
    if confidence:
        avg_conf = round(sum(confidence.values()) / len(confidence), 4)

    return {
        "stock_code": fields.get("code", ""),
        "stock_name": fields.get("name", ""),
        "change_pct": _parse_percent(fields.get("change_pct")),
        "current_price": _parse_number(fields.get("price")),
        "volume_ratio": _parse_number(fields.get("volume_ratio")),
        "turnover": _parse_percent(fields.get("turnover_pct")),
        "main_inflow": _parse_unit_number_to_float(fields.get("main_net_inflow")),
        "industry": fields.get("industry", ""),
        "row_index": row_index,
        "fields": fields,
        "raw_columns": raw,
        "ocr_confidence": avg_conf,
        "parser_version": "stock_table_dynamic_v1",
    }


def _post_callback(callback_url: str, payload: dict) -> None:
    """POST callback to MoneyMoneyHome using urllib."""
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            callback_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as exc:
        print(f"[ExternalOCR] Callback failed: {exc}", flush=True)


def _process_external_recognition(
    image_path: str,
    batch_id: str,
    trade_date: str,
    captured_at: str,
    callback_url: str,
) -> None:
    """Run OCR in background and callback MoneyMoneyHome."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _upsert_task(batch_id=batch_id, status="loading_model", progress=5, started_at=now)
    try:
        print(f"[ExternalOCR] Processing {batch_id}: {image_path}", flush=True)
        start = time.time()

        ocr_engine = get_ocr_engine()
        _upsert_task(batch_id=batch_id, status="processing", progress=30)
        with _OCR_RECOGNITION_LOCK:
            result = parse_image(
                image_path=image_path,
                schema_path=str(SCHEMA_PATH),
                ocr_engine=ocr_engine,
                stock_dict_path=str(STOCK_DICT_PATH),
                snapshot_time=captured_at,
                min_confidence=0.85,
            )

        elapsed = round(time.time() - start, 2)
        snapshots = [
            _convert_record_to_snapshot(r, i)
            for i, r in enumerate(result.records)
        ]

        print(f"[ExternalOCR] {batch_id}: {len(snapshots)} stocks, {elapsed}s", flush=True)

        _upsert_task(batch_id=batch_id, status="callback", progress=90)
        _post_callback(callback_url, {
            "batch_id": batch_id,
            "trade_date": trade_date,
            "status": "completed",
            "snapshots": snapshots,
            "error": "; ".join(result.warnings) if result.warnings else None,
        })

        _upsert_task(
            batch_id=batch_id,
            status="completed",
            progress=100,
            completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            duration_seconds=elapsed,
            stock_count=len(snapshots),
            error="; ".join(result.warnings) if result.warnings else None,
        )

    except Exception as exc:
        print(f"[ExternalOCR] {batch_id} failed: {exc}", flush=True)
        _upsert_task(batch_id=batch_id, status="callback", progress=90)
        _post_callback(callback_url, {
            "batch_id": batch_id,
            "trade_date": trade_date,
            "status": "failed",
            "snapshots": [],
            "error": str(exc),
        })
        _upsert_task(
            batch_id=batch_id,
            status="failed",
            progress=100,
            completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            error=str(exc),
        )


@app.route("/recognize", methods=["POST"])
def recognize():
    """Accept a screenshot path from MoneyMoneyHome and process it asynchronously.

    Request body (JSON):
        {
            "image_path": "/path/to/screenshot.png",
            "batch_id": "2025-05-31_143052...",
            "trade_date": "2025-05-31",
            "captured_at": "2025-05-31 14:30:52",
            "callback_url": "http://127.0.0.1:8000/api/v1/moneymoney/news/stock-list-monitor/callback"
        }
    """
    data = request.get_json(force=True) or {}
    image_path = data.get("image_path")
    batch_id = data.get("batch_id")
    trade_date = data.get("trade_date")
    captured_at = data.get("captured_at")
    callback_url = data.get("callback_url")

    if not image_path or not batch_id or not callback_url:
        return jsonify({"status": "error", "message": "缺少必要参数: image_path, batch_id, callback_url"}), 400

    if not Path(image_path).exists():
        return jsonify({"status": "error", "message": f"图片不存在: {image_path}"}), 400

    # Record task status
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _upsert_task(
        batch_id=batch_id,
        trade_date=trade_date,
        image_path=image_path,
        callback_url=callback_url,
        status="accepted",
        created_at=now,
        started_at=None,
        completed_at=None,
        duration_seconds=None,
        stock_count=None,
        error=None,
    )

    # Process in background so HTTP response returns immediately
    t = threading.Thread(
        target=_process_external_recognition,
        kwargs={
            "image_path": image_path,
            "batch_id": batch_id,
            "trade_date": trade_date,
            "captured_at": captured_at,
            "callback_url": callback_url,
        },
        daemon=True,
    )
    t.start()

    return jsonify({"status": "accepted", "batch_id": batch_id})


if __name__ == "__main__":
    port = int(os.environ.get("FLASK_PORT", "5000"))
    app.run(debug=True, use_reloader=False, port=port)

# stock-table-ocr-dynamic

一个用于中国股票行情截图的 Python 结构化识别项目。

核心目标不是“整图 OCR 输出文本”，而是：

```text
行情截图 → 动态定位表格结构 → 每一行解析为一只股票 → 每一列按表头字段填充 → 输出 CSV / Excel / JSONL / 个股 JSON
```

## 关键原则

本项目采用 **固定结构，不固定像素** 的方案：

- 固定的是：表头字段、字段顺序、字段类型、校验规则、输出结构。
- 不固定的是：图片宽度、图片高度、列像素坐标、行像素坐标、显示器分辨率、系统缩放比例。

程序运行时会动态计算当前截图中的：

- 表格竖向线位置，也就是列边界；
- 表格横向线位置，也就是行边界；
- 如果表格线检测失败，可通过 OCR 表头和股票代码行锚点兜底。

## 目录结构

```text
stock_table_ocr_dynamic/
  src/stock_table_ocr/
    cli.py                  # 命令行入口
    parser.py               # 主解析流程
    line_detector.py         # OpenCV 动态表格线检测
    header_locator.py        # OCR 表头定位兜底
    ocr_engine.py            # PaddleOCR 封装
    normalizers.py           # 字段标准化
    validators.py            # 字段和行级校验
    outputs.py               # CSV/Excel/JSONL/个股 JSON 输出
  configs/
    stock_table_schema.json  # 固定字段结构，不包含固定像素坐标
  data/
    stock_code_name_sample.csv
  samples/
    white_market_table_sample.png
  tests/
```

## 安装

建议使用 Python 3.10 或 3.11。

```bash
cd stock_table_ocr_dynamic
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
pip install -e .
```

如果 PaddleOCR / paddlepaddle 在你的 Mac 环境安装失败，先单独按照 PaddleOCR / PaddlePaddle 对应平台安装说明处理，然后再执行：

```bash
pip install -e .
```

## 快速测试：只检测表格结构，不跑 OCR

这个命令不需要 PaddleOCR 成功安装，适合先看动态表格线检测是否有效。

```bash
python -m stock_table_ocr.cli \
  --image samples/white_market_table_sample.png \
  --schema configs/stock_table_schema.json \
  --ocr null \
  --detect-only \
  --out output/test_detect
```

输出：

```text
output/test_detect/runtime_layout.json
```

里面会记录本次截图动态计算出来的列边界、行边界和 warnings。

## 正式 OCR 识别

```bash
python -m stock_table_ocr.cli \
  --image samples/white_market_table_sample.png \
  --schema configs/stock_table_schema.json \
  --stock-dict data/stock_code_name_sample.csv \
  --out output/run_001 \
  --snapshot-time "2026-05-29 10:30:00" \
  --debug-cells
```

默认 OCR 配置面向表格截图的连续识别场景做了优化：

- 关闭 PaddleOCR 的文档方向分类、文档矫正和文本行方向分类；
- 默认使用 `PP-OCRv5_mobile_det` + `PP-OCRv5_mobile_rec`；
- 默认设置 `text_recognition_batch_size=1`，在 Mac CPU 环境下对大量小文本块更快；
- Web 服务会在进程内复用同一个 OCR 引擎，避免每次上传都重新加载模型。

可通过环境变量覆盖模型和识别批量大小：

```bash
export STOCK_TABLE_OCR_DET_MODEL=PP-OCRv5_mobile_det
export STOCK_TABLE_OCR_REC_MODEL=PP-OCRv5_mobile_rec
export STOCK_TABLE_OCR_REC_BATCH_SIZE=1
```

如果更看重极限速度、能接受更多低置信度复核项，可临时尝试：

```bash
export STOCK_TABLE_OCR_DET_MODEL=PP-OCRv3_mobile_det
export STOCK_TABLE_OCR_REC_MODEL=PP-OCRv3_mobile_rec
```

输出包括：

```text
output/run_001/
  market_table_YYYYMMDD_HHMMSS.csv
  market_table_YYYYMMDD_HHMMSS.xlsx
  market_table_YYYYMMDD_HHMMSS.jsonl
  runtime_layout_YYYYMMDD_HHMMSS.json
  stocks/
    600105_永鼎股份.json
    002130_沃尔核材.json
  review/
    ocr_error_cells_YYYYMMDD_HHMMSS.csv
    correction_log_YYYYMMDD_HHMMSS.md
  debug_cells/
    row_000_code.png
    row_000_name.png
    ...
```

## 输出数据说明

每一行股票会被解析为一个 `StockRecord`，结构如下：

```json
{
  "snapshot_time": "2026-05-29 10:30:00",
  "source_image": "samples/white_market_table_sample.png",
  "fields": {
    "code": "600105",
    "name": "永鼎股份",
    "change_pct": "-1.48%",
    "price": "47.81"
  },
  "raw_cells": {
    "code": "600105",
    "name": "永鼎股份"
  },
  "confidence": {
    "code": 0.99,
    "name": 0.96
  },
  "validation_errors": []
}
```

## 字段校验规则

当前内置规则：

- `code`：必须是 6 位数字；
- `name`：优先用 `stock_code_name_sample.csv` 中的股票代码字典修正；
- 百分比字段：标准化为 `+1.23%` / `-1.23%`；
- `委比%`：范围校验为 -100 到 100；
- `换手%`、`量比`：不应为负；
- 金额和数量字段：保留 `万`、`亿`、`K`、`↑`、`↓`；
- 行级校验：`涨幅%` 和 `涨跌` 方向冲突时标记 warning。

## 替换为完整 A 股代码表

`data/stock_code_name_sample.csv` 只是示例。你后续应该替换为完整 A 股代码名称表，至少包含：

```csv
code,name,industry
600105,永鼎股份,通信设备
002130,沃尔核材,通信设备
```

程序会用 `code` 作为主键，自动修正 OCR 识别出来的股票名称。

## 开发建议

第一步先运行 `--detect-only`，确认 `runtime_layout.json` 中动态检测出的列数和行数是否合理。第二步加 `--debug-cells`，查看每个单元格裁剪是否准确。只有裁剪准确，OCR 才能稳定。

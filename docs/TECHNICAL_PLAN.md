# 技术方案：固定结构、动态定位的行情截图结构化识别

## 1. 问题定义

输入是白底股票行情列表截图。每一行代表一只股票，每一列对应表头字段。目标是输出结构化数据，而不是普通 OCR 文本。

核心输出：

- `market_table.csv`
- `market_table.xlsx`
- `market_table.jsonl`
- `stocks/<code>_<name>.json`
- `review/ocr_error_cells.csv`
- `review/correction_log.md`

## 2. 不采用固定像素坐标

不同显示器、不同系统缩放、不同截图方式会导致图片尺寸变化，所以不能把 `x1=0, x2=86` 作为核心配置。

本项目只固定：

- 表头字段；
- 字段顺序；
- 字段类型；
- 字段校验规则；
- 输出 schema。

每张图片的表格区域、列边界、行边界都在运行时动态检测。

## 3. 动态定位策略

### 3.1 列边界

优先使用 OpenCV 形态学操作检测竖向表格线。

如果竖向线检测不足，使用 OCR 表头文字框中心点推断列边界。

如果 OCR 表头也失败，使用相对宽度兜底，并输出 warning。

### 3.2 行边界

优先使用 OpenCV 形态学操作检测横向表格线。

如果横向线检测不足，使用代码列 OCR 识别 6 位股票代码，根据代码文字框的 y 中心点推断每一行。

## 4. 单元格识别

每个单元格单独裁剪、单独 OCR。禁止整图 OCR 后直接拼接文本。

```text
for row in rows:
  for col in columns:
    cell = crop(row, col)
    text, confidence = ocr(cell)
    field = normalize_by_type(col.type, text)
```

## 5. 字段校验

- 股票代码：6 位数字；
- 股票名称：通过代码表校正；
- 百分比：统一为 `%` 格式；
- 金额/数量：保留单位；
- 委比：-100 到 100；
- 行级方向：涨幅和涨跌方向应基本一致。

## 6. 人工复核闭环

所有低置信度、字段格式异常、代码名称不匹配、必填字段为空的结果都会进入：

```text
review/ocr_error_cells_*.csv
review/correction_log_*.md
```

第一版没有实现 Web 复核页面，但输出文件已经为后续人工复核或 Web UI 预留。

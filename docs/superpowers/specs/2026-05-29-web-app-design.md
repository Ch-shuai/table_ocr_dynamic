# Stock Table OCR Web 应用设计文档

## 背景

为 `stock-table-ocr-dynamic` 项目构建一个 Web 界面，用于上传股票行情截图、配置参数、执行 OCR 解析，并在页面上展示所有输出内容。

## 目标

- 零配置启动 Web 服务即可使用
- 所有 CLI 输出内容均在页面上可视化
- 不保存历史记录，刷新即清空
- 内部测试工具，简洁优先

## 技术栈

- **后端**: Flask + Jinja2（服务端渲染）
- **前端**: 原生 HTML/CSS/JS（无框架）
- **样式**: 原生 CSS，简洁实用

## 文件结构

```
web/
  app.py              # Flask 入口
  __init__.py
  templates/
    base.html         # 基础布局
    index.html        # 上传表单 + 结果展示
  static/
    style.css         # 样式
    app.js            # Tab 切换、交互
uploads/              # 上传图片临时目录（.gitignore）
output/               # 解析输出（复用现有）
```

## 路由设计

| 路由 | 方法 | 说明 |
|------|------|------|
| `GET /` | 渲染上传表单页 | |
| `POST /parse` | 接收图片 + 参数 → 执行解析 → 重定向 | |
| `GET /result/<run_id>` | 展示该次解析的全部结果 | |
| `GET /cell_image/<run_id>/<filename>` | 返回单元格裁剪图 | |
| `GET /original_image/<run_id>` | 返回原始上传图片 | |

## 页面布局

顶部：上传区域（拖拽/点击）
中部：参数配置折叠面板
按钮：运行解析
底部：结果区（Tab 切换）

## Tab 设计（7 个）

| Tab | 内容 |
|-----|------|
| 原始预览 | 上传图片 + 行列线叠加 |
| 数据表格 | CSV 渲染成 `<table>` |
| JSONL | 每行一个 `<pre>` 代码块 |
| 布局坐标 | columns + rows 坐标表格 |
| 错误报告 | 低置信度 + 修正日志 + 校验错误 |
| 单元格图片 | 按行折叠面板，缩略图网格 |
| 单股 JSON | 每只股票的 JSON，可折叠 |

## 参数配置

- 快照时间（文本输入）
- 最低置信度（滑块 0.5~1.0，默认 0.85）
- 二值化开关（checkbox）
- detect-only 模式（checkbox）

## 数据流

```
上传图片 → 保存到 uploads/<run_id>/
→ 调用 parse_image() → 输出到 output/<run_id>/
→ 读取所有输出文件 → 注入模板渲染
```

## 图片叠加线实现

CSS `position: relative` 容器 + `position: absolute` 半透明 div 表示行列边界。

## 单元格图片展示

每行一个 `<details>` 折叠面板，展开后显示该行的单元格缩略图网格。

## 不保存历史

- 不引入数据库
- 运行 ID = 时间戳目录
- 页面刷新后不保留任何状态

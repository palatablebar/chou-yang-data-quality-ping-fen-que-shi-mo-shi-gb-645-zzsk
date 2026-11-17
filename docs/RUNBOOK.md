# 运行手册 qualiscore

## 1 启动

```bash
docker compose up -d --build
curl -s http://127.0.0.1:18204/api/health
open http://127.0.0.1:18204/
```

首次打开库里没有任何运行记录，页面只有一个空态与采信表单；选样例点
「采信并评分」即产生第一条记录。数据落在命名卷 `qualiscore-data` 的
`/data/qualiscore.sqlite`。

## 2 重建数据库

```bash
docker compose down -v          # 删掉命名卷
docker compose up -d --build    # 新库，页面回到空态
```

只想清空运行记录、保留上传的数据集时，删 SQLite 文件即可（下一次启动会建表）。

## 3 跑主流程（命令行）

```bash
# 采信脏样例
curl -s -X POST http://127.0.0.1:18204/api/datasets/import \
  -H 'Content-Type: application/json' -d '{"sample":"tickets_dirty.csv"}'

# 评分（默认样例）
curl -s -X POST http://127.0.0.1:18204/api/score \
  -H 'Content-Type: application/json' -d '{"sample":"tickets_dirty.csv"}'

# 上传自己的文件
curl -s -X POST http://127.0.0.1:18204/api/datasets/upload \
  -F 'file=@sample_data/tickets_dirty.csv' -F 'encoding=utf-8'

# 导出
curl -s -o /tmp/report.csv http://127.0.0.1:18204/api/export/report.csv
curl -s http://127.0.0.1:18204/api/export/manifest.json
```

## 4 样例

| 文件 | 用途 | 期望结果 |
|---|---|---|
| `tickets_dirty.csv` | 主演示：哨兵、空白、重复、冲突、越界、分段、截断 | 65.24 分 C 级，隔离 3 行，2 段 |
| `tickets_clean.csv` | 干净对照 | 100.00 分 A 级 |
| `tickets_gbk.csv` | GB18030 + 中文表头 | 采信成功，标 `K_ALIAS_MAPPED` |
| `tickets_bom.csv` | BOM + CRLF | 采信成功，标 `K_BOM_STRIPPED` |
| `tickets_truncated.csv` | 末行截断 | 隔离 1 行，标 `K_TRUNCATED_TAIL` |
| `tickets_constant.csv` | 常量列 + 全空列 | 70.00 分 C 级，缺失维封顶 |
| `tickets_header_only.csv` | 仅表头 | 422 `E_HEADER_ONLY` |
| `tickets_blank.csv` | 全空行 | 422 `E_ALL_BLANK` |
| `tickets_empty.csv` | 空文件 | 422 `E_EMPTY_FILE` |

## 5 常见失败

| HTTP | 原因码 | 处理 |
|---|---|---|
| 422 | `E_EMPTY_FILE` | 文件是 0 字节，换一份 |
| 422 | `E_HEADER_ONLY` | 只有表头，导出补上数据行 |
| 422 | `E_ALL_BLANK` | 数据行全空，检查导出是否只写了分隔符 |
| 422 | `E_HEADER_INVALID` | 缺必填列；`detail.missing` 列出缺哪几列 |
| 422 | `E_DECODE` | 编码不在 UTF-8 / GB18030 内，先转码再传 |
| 404 | `E_SAMPLE_UNKNOWN` | 样例名不在白名单，用 `/api/datasets` 看可用项 |
| 409 | `E_STALE_RUN` | 页面版本落后；刷新后重跑，别用旧页面覆盖 |
| 404 | `E_RUN_NOT_FOUND` | 还没有运行记录，先跑一次评分 |

## 6 测试

```bash
docker compose exec -T app python -m pytest -q
```

本地（不启容器）也可以：

```bash
python3 -m pytest -q
```

## 7 日志与排查

- 容器日志：`docker compose logs -f app`。
- 分数异常先看 `/batches` 的阈值表与五项对账；对账不平说明有单元格被重复计数。
- 离群数为 0 时先看 `/outliers` 的「退化列」：满意度一类 1-5 分刻度默认判退化。
- 每份导出都能在 `/api/export/manifest.json` 里找到同一次运行的 `run_id` 与输入摘要。

# 深度登记 qualiscore（抽样数据质量评分与缺失模式）

- 规模：中型（7 个功能模块 / 6 个应用页 / 97 条测试）
- 核心规则：**MAD 稳健 z + 退化回退 + 封顶加权评分**。逐格先判三态（缺失 / 格式不合格 / 有值），
  再按列算中位数与 MAD；`z = 0.6745 × (x − 中位数) / MAD`，MAD=0 时回退 `spread = 0.6745 × IQR / 1.349`，
  离散度低于「列刻度 × 5」或 MAD 与 IQR 同为 0 判退化；评分 = 100 − 缺失 30 − 重复 25 − 离群 20 − 格式 25，
  每维按容忍度封顶，比率与扣分全用 Decimal。
- 使用者与工作流：客服质量组每月抽 1.2 万行工单导出一份 CSV，原先靠人眼翻缺失、重复和离群；
  现在一次采信得到分数、等级、逐列证据与运行清单，每个数字能追回源文件行号与原因码。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 数据采信 | 选样例或上传 CSV，看逐行诊断与隔离行 | POST /api/datasets/import、POST /api/datasets/upload、GET /api/datasets/{name}/rows | `app/modules/m1_ingest/decode.py` `app/modules/m1_ingest/reader.py` `app/modules/m1_ingest/sniff.py` `app/modules/m1_ingest/service.py` | `tests/test_m1_ingest.py` |
| M2 字段画像 | 看每列填充率、基数、格式率、取值范围 | GET /api/profile、POST /api/profile/cell、页面 /profile | `app/modules/m2_profile/formats.py` `app/modules/m2_profile/column_stats.py` `app/modules/m2_profile/profile.py` `app/modules/m2_profile/service.py` | `tests/test_m2_profile.py` |
| M3 缺失模式 | 看单元格账、连续缺失段、共缺对 | GET /api/missing、页面 /missing | `app/modules/m3_missing/cells.py` `app/modules/m3_missing/runs.py` `app/modules/m3_missing/matrix.py` `app/modules/m3_missing/service.py` | `tests/test_m3_missing.py` |
| M4 重复判定 | 看全行重复组与同键冲突的原值对照 | GET /api/duplicates、页面 /duplicates | `app/modules/m4_duplicates/hashdup.py` `app/modules/m4_duplicates/keydup.py` `app/modules/m4_duplicates/groups.py` `app/modules/m4_duplicates/service.py` | `tests/test_m4_duplicates.py` |
| M5 稳健离群 | 看逐列中位数、MAD、回退方法与离群格 | GET /api/outliers、页面 /outliers | `app/modules/m5_outliers/robust.py` `app/modules/m5_outliers/zscore.py` `app/modules/m5_outliers/flags.py` `app/modules/m5_outliers/service.py` | `tests/test_m5_outliers.py` |
| M6 评分与批次 | 跑一次评分、查运行历史、看五项对账、重跑 | POST /api/score、GET /api/batches、GET /api/reconcile、页面 /batches | `app/modules/m6_score/score.py` `app/modules/m6_score/grade.py` `app/modules/m6_score/runstore.py` `app/modules/m6_score/service.py` | `tests/test_m6_score.py` |
| M7 报告导出 | 看报告页、导出六种 CSV 与运行清单 | GET /、GET /api/export/* | `app/modules/m7_export/report.py` `app/modules/m7_export/csv_out.py` `app/modules/m7_export/manifest_out.py` `app/modules/m7_export/service.py` | `tests/test_m7_export.py` |

端到端：`tests/test_e2e.py`（HTTP 走完采信 → 评分 → 六页 200 → 八种导出；含上传、失败输入、陈旧版本 409）。
不变量：`tests/test_invariants.py`（行分区、单元格分区、分数闭合、幂等重跑、重复分区、顺序无关、缺失扣分单调）。

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-02 | Excel 另存的文件头带 UTF-8 BOM | 首列名变成 `\ufeffticket_id`，按列名取值全空 | 解码即剥 BOM，并对首格再清一次不可见字符 | `app/modules/m1_ingest/decode.py`、`app/modules/m1_ingest/sniff.py` | `tests/test_m1_ingest.py::test_bom_stripped_before_header_mapping` |
| TRAP-05 | 行尾多一个分隔符、列数与表头不一致 | 静默补空值，或整行错位后参与统计 | 严格列数校验，整行进隔离区并保留原值与行号 | `app/modules/m1_ingest/sniff.py` | `tests/test_m1_ingest.py::test_column_count_mismatch_isolated_with_lineno` |
| TRAP-06 | `1,204.5`、`１，２０４.５`、`1 204.5` 混写 | `Decimal()` 抛异常，或截断成 1204 | NFKC 折全角 → 去千分位与空白 → Decimal → 按列刻度量化 | `app/modules/m2_profile/formats.py` | `tests/test_m2_profile.py::test_thousands_and_fullwidth_normalized`、`tests/test_m4_duplicates.py::test_hash_ignores_raw_formatting` |
| TRAP-07 | `-` / `N/A` / `未知` / 空白串混在取值里 | 被当成 0 参与均值，或整列变成空 | 空串 / 空白串 / 哨兵三态分开，统一为缺失并留原因码；`0` 仍是有值 | `app/modules/m2_profile/formats.py`、`app/config.py` | `tests/test_m2_profile.py::test_sentinel_three_state_codes` |
| TRAP-09 | 19 位工单号、带前导零的客户号 | 过 `int()` 掉精度或丢零，对不上原文件 | 全链路按字符串保形，只做格式校验不做数值化 | `app/modules/m2_profile/formats.py`、`app/modules/m1_ingest/reader.py` | `tests/test_m1_ingest.py::test_bigint_ticket_id_preserved` |
| TRAP-10 | 比率与扣分累加 | float 累加后总分与分项差 0.01 | 比率 0.0001、分数 0.01，全部 Decimal，闭合断言 | `app/modules/m6_score/score.py` | `tests/test_m6_score.py::test_penalty_rates_and_penalties`、`tests/test_m6_score.py::test_score_closure_and_grade` |
| TRAP-14 | 同一工单号两条不同取值 | 后写覆盖，前一条消失且不留痕 | 两行都保留原值，逐列列出冲突列，交人工复核 | `app/modules/m4_duplicates/keydup.py` | `tests/test_m4_duplicates.py::test_key_conflict_keeps_both_rows_and_fields` |
| TRAP-18 | 0 字节文件、仅表头、全空行 | 三种都返回「成功导入 0 行」，或直接除零 | 三个文件级原因码分开返回，整批不落数据 | `app/modules/m1_ingest/sniff.py` | `tests/test_m1_ingest.py::test_empty_states_return_distinct_codes` |
| TRAP-19 | 一个单元格同时像缺失、越界、离群 | 按代码顺序覆盖，分项之和大于总分 | 固定优先级缺失 > 格式不合格 > 离群，一格只进一个桶 | `app/modules/m5_outliers/flags.py`、`app/modules/m2_profile/formats.py` | `tests/test_m5_outliers.py::test_priority_missing_over_range_over_outlier` |
| TRAP-22 | 同一组重复行打乱顺序 | 代表行随顺序变化，导出结果不可复现 | 代表行取最小原始行号，组排序按代表行号 | `app/modules/m4_duplicates/groups.py`、`app/modules/m4_duplicates/hashdup.py` | `tests/test_m4_duplicates.py::test_order_independence_of_groups` |
| TRAP-26 | 旧页面提交覆盖新结果 | 后提交无条件写入，新版本被旧数据顶掉 | 同名数据集版本自增，`expected_version` 落后即 409 | `app/modules/m6_score/runstore.py` | `tests/test_m6_score.py::test_stale_submission_rejected`、`tests/test_e2e.py::test_stale_version_conflict_over_http` |

## 对账规则

五项账在报告页、批次页、`/api/reconcile` 与运行清单里同源显示（脏样例实测值）：

| 账 | 左侧 | 右侧 | 脏样例 |
|---|---|---|---|
| 数据行账 | 原始记录 | 采纳 + 隔离 + 空行 | 55 = 51 + 3 + 1 |
| 采纳行账 | 采纳行 | 唯一 + 重复 | 51 = 50 + 1 |
| 单元格账 | 单元格 | 缺失 + 有值 | 510 = 14 + 496 |
| 有值格账 | 有值 | 合格 + 格式不合格 | 496 = 494 + 2 |
| 分数账 | 100 | 总分 + 扣分 | 100 = 65.24 + 34.76 |

## 反例与不变量

- 反例（朴素实现会挂）：`tests/test_m1_ingest.py::test_quoted_newline_kept_in_one_record`（`splitlines` 把一条记录切成两条）、
  `tests/test_m1_ingest.py::test_declared_gbk_on_utf8_file_surfaces_as_format_errors`（声明错编码不会崩，但乱码必须被格式维抓出）、
  `tests/test_m5_outliers.py::test_constant_column_is_degenerate`（均值+标准差在常量列上除零）、
  `tests/test_m6_score.py::test_stale_submission_rejected`（后写覆盖会顶掉新版本）。
- 不变量：`tests/test_invariants.py::test_rows_partition_holds_for_all_samples`（行分区）、
  `tests/test_invariants.py::test_cells_partition_holds`（单元格分区）、
  `tests/test_invariants.py::test_score_closure_for_all_samples`（分数闭合）、
  `tests/test_invariants.py::test_rerun_keeps_counts_and_score`（幂等）、
  `tests/test_invariants.py::test_score_is_order_independent`（顺序无关）、
  `tests/test_invariants.py::test_missing_penalty_is_monotonic`（单调）。
- 端到端：`tests/test_e2e.py::test_full_pipeline_over_http`。

## 已知不覆盖

- 只按整份文件重算，不支持增量追加与断点续跑；同名数据集重跑即全量重算。
- 列契约固定 10 列（`app/config.py`），新增列按未知列忽略而不报错；自定义列需要改契约与别名。
- 权重、容忍度、等级阈值写在配置里，改完必须重新运行；不支持页面上调参。
- 只处理 UTF-8 / GB18030 两类编码；UTF-16、Big5、Shift-JIS 会落到 `E_DECODE`。
- 稳健离群只支持数值列；日期列不做离群判定，文本列只做基数与格式检查。
- 缺失模式只看「同列连续缺失」，不做跨文件的缺失趋势对比。

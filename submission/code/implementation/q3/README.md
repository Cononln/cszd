# Q3：通信中继联合调度

Q3 在不改动冻结 Q2 路线、运输物理、舰队和电池规则的前提下，完成通信中继的联合可行性评价。

正式流程为：冻结 Q2 运输状态 → C2-A 受约束时间修复 → 有限 C2-B 组合搜索 → 真实 Q3-B 中继解码 → 独立 validator → final audit → 单一正式 JSON → 图表与表格。

## 正式复现

```powershell
$env:PYTHONPATH = "$PWD\implementation\q3\code"
python -m q3.run_q3_final --mode formal --clean
```

该命令只清理并重建 `implementation/q3/results/`，执行 C2-A/C2-B 的真实候选评估，并将图表和表格作为 `q3_final.json` 的只读派生物并行生成。

## Clean run

```powershell
$env:PYTHONPATH = "$PWD\implementation\q3\code"
python -m q3.run_q3_final --mode reproduce
```

它在 `implementation/q3/reproducibility/clean_results/` 从空输出目录重新生成全部证据，不复用正式结果缓存。

## 主要正式产物

- `results/q3_final.json`：唯一正式数字来源。
- `results/q3_final_audit.json`：冻结完整性、独立 validator、交付物一致性审计。
- `results/q3_feasible_pool.json` 与 `results/q3_failure_taxonomy.json`：完整候选证据。
- `results/figures/`：Q3 正式图、SVG/PDF/TIFF 与版面 QA。
- `results/tables/`：正式 CSV 和 Markdown 表格。
- `results/Q3_FREEZE_REPORT.md`：冻结结论与机器可读证据索引。

Q3 的正式图表和表格只读取 `q3_final.json`；它们不会读取临时候选结果。

当前正式冻结链为 schema `1.2`、正式结果修订 `c7880a36e1f5e9efb39f0d6d6be9d38b9638d80a`、
选定解 `C2A-BASE`。`results/Q3_FREEZE_REPORT.md` 必须同时报告 `Q3 STATUS: FROZEN`
和 `CANDIDATE INTEGRITY: PASS`。

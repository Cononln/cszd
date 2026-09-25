# Q4：救援任务分区与资源配置

Q4 只继承 Q3 已独立验证的 `q3_final.json.selected_solution`。它将 15 个
服务区按冻结运输架次的服务区耦合关系划分为 2 组和 3 组，比较各组独立执行、
且资源不得跨组调配时所需的运输无人机、共享电池、中继无人机和中继能源组件。

正式入口：

```powershell
$env:PYTHONPATH = "$PWD\implementation\q4\code"
python -m q4.run_q4_final --mode formal --clean
```

Clean reproduction and its semantic consistency audit:

```powershell
$env:PYTHONPATH = "$PWD\implementation\q4\code"
python -m q4.run_q4_final --mode reproduce
python -m q4.compare_q4_reproduction
```

Q4 从不读取 Q3 候选搜索、候选日志或缓存文件；`implementation/q3/results/q3_final.json`
是唯一允许的 Q3 上游输入。

`results/Q4_FREEZE_REPORT.md` records the frozen status. The clean output is
regenerated under `reproducibility/clean_results/`; only its compact evidence
is versioned because the complete output is deterministically reproduced by
the commands above.

The frozen selections are `Q4-2G-00003` and `Q4-3G-00001`.  The freeze report
must state both `Q4 STATUS: FROZEN` and `UPSTREAM Q3 REFRESH: PASS`.

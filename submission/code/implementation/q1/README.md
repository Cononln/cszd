# Q1 正式实现

Q1 已冻结，正式结果只以 `results/q1_final.json` 为准。

## 模型与验证

`code/q1/audit_physics.py` 审查基础物理模型；正式解在其基础上完成最大安全载荷、
跨机型组批、目标比较和敏感性验证。物理检查包括：

- O01 到 15 个服务区的 DEM 航段；
- 沿途最高 DEM + 50 m 巡航高度；
- O01/服务区作业高度及爬升、下降高度；
- 载荷相关等效航程的正值和单调性；
- 去程带载荷、返程空载的能耗口径；
- 返航安全余量 `(1-rho) E_use`。

运行：

```powershell
python implementation/q1/code/q1/audit_physics.py
```

结果写入 `results/`。`q1_final.json` 的 `status=PASS` 且全部 checks 为 true 表示
Q1 冻结有效。

## Q1 结果与出图

冻结结果的统一绘图入口为 `code/q1/plot_q1_results.py`。该脚本仅读取
`results/` 下的 Q1 CSV/JSON，输出主图、补充图及 PDF/SVG/PNG 和审计清单到
`figures/`，不会重新运行求解器。

```powershell
python implementation/q1/code/q1/plot_q1_results.py
```

正式求解入口为 `python implementation/q1/code/q1/solve_q1.py`；评审默认应先运行
项目级 audit-only，而不是重算优化。

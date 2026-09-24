# Q1 正式实现

当前只维护数学建模 D 题的 Q1，采用逐问验收制。

## Phase Q1-1

`code/q1/audit_physics.py` 只检查基础物理模型，不进行组批，也不反解最大安全载荷。检查内容包括：

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

结果写入 `results/`。Q1-1 当前全部 PASS；用户确认后才进入 Q1-2。

## Q1 结果与出图

冻结结果的统一绘图入口为 `code/q1/plot_q1_results.py`。该脚本仅读取
`results/` 下的 Q1 CSV/JSON，输出主图、补充图及 PDF/SVG/PNG 和审计清单到
`figures/`，不会重新运行求解器。

```powershell
python implementation/q1/code/q1/plot_q1_results.py
```

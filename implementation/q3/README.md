# Q3-A 通信约束与中继联合建模基础

本目录只实现 Q3-A 的通信物理、连续轨迹、DEM 视线、双向链路预算、中继候选和能源审计。
它复用 `implementation/q1/code/common` 与 `implementation/q2/code/q2`，不固定 Q2 formal 解，
也不进入 Q3-B/Q3-C 的联合优化。

运行：

```powershell
.venv\Scripts\python.exe implementation/q3/code/q3/audit_q3_a.py
```

正式输出位于 `implementation/q3/results/`：数据审计、通信单元测试、真实路线盲区与独立区间验证、
步长敏感性、逐候选中继复核、端点缓冲敏感性、全部 Q2 基线架次的 Direct-only 审计及 Q3-A 总结报告。

通信传播损耗使用通信端点间的三维欧氏距离；DEM 视线剖面仍严格以水平距离参数化。
本目录在 Q3-A 审计通过后停止，不包含 Q3-B/C 的联合调度或 ALNS。

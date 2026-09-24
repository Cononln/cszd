# Q3-A 通信约束与中继联合建模基础

本目录只实现 Q3-A 的通信物理、连续轨迹、DEM 视线、双向链路预算、中继候选和能源审计。
它复用 `implementation/q1/code/common` 与 `implementation/q2/code/q2`，不固定 Q2 formal 解，
也不进入 Q3-B/Q3-C 的联合优化。

运行：

```powershell
.venv\Scripts\python.exe implementation/q3/code/q3/audit_q3_a.py
```

正式输出位于 `implementation/q3/results/`：数据审计、通信单元测试、真实路线盲区、步长敏感性、
中继候选审计和 Q3-A 总结报告。

# D 题代码实现

旧的 A/raw 与 B/super 两套上传代码已清理。当前仓库按照逐问验收制，只维护
Q1 的正式实现；Q2–Q4 在 Q1 全部 PASS 前不进入代码修改。

## Q1

- `q1/code/common/`：数据读取、DEM 航段、巡航高度、爬升/下降、载荷相关航程和能耗公共层；
- `q1/code/q1/audit_physics.py`：Phase Q1-1 基础物理模型审查；
- `q1/results/`：机器可读检查结果、航段参数表和 Markdown 审查报告；
- `q1/requirements.txt`：读取 DEM 和运行审查所需的依赖。

运行：

```powershell
python implementation/q1/code/q1/audit_physics.py
```

Q1-1 已通过数据、DEM、巡航高度、能耗、载荷航程单调性和返航安全余量检查。
最大安全载荷和组批代码需在阶段确认后再加入。

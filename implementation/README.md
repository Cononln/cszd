# D 题代码实现

旧的 A/raw 与 B/super 两套上传代码已清理。当前仓库按照逐问验收制维护唯一正式
实现：Q1 已冻结，Q2 当前只进入 Q2-A 基础阶段；Q3/Q4 暂不修改核心代码。

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

## Q2-A

- `q2/code/q2/`：多点路线、硬截止、资源解码和 ALNS 的阶段化接口骨架；
- `q2/results/`：A/B 供体审计、约束登记和真实数据审计；
- 当前不运行 Q2 正式优化，不生成 Q2 最优路线。

运行 Q2-A 数据审计：

```powershell
python implementation/q2/code/q2/audit_q2_a.py
```

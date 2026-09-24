# Q2 正式实现（Q2-A 基础阶段）

Q2 是异构运输无人机的多点、多架次、共享电池联合调度问题。本目录是唯一正式
Q2 实现的入口。A/raw 与 B/super 仅作为供体和审计依据，不在仓库中维护第二套
正式求解器。

## 当前阶段

当前分支为 `q2/q2-a-foundation`，只完成 Q2-A：

- 对 GitHub 的 Q1 正式公共层和本地 A/B 供体进行来源审计；
- 登记 HARD、DERIVED 和 MODELING CHOICE 约束；
- 复用 `implementation/q1/code/common/`，不复制 DEM、航段和能耗公式；
- 固定当前字段下的硬截止接口；
- 建立多点路线、调度和验证器的正式接口骨架；
- 输出真实数据审计，不运行正式 Q2 优化，不生成 Q2 最优解。

Q2-A 的机器可读审计在 `results/q2_data_audit.json`，供体和约束审计分别在
`results/q2_code_donor_audit.md` 与 `results/q2_constraint_registry.md`。

## Q1 公共层继承

Q2 通过路径导入 Q1 的正式公共模块：

```text
implementation/q1/code/common/data.py
implementation/q1/code/common/dem.py
implementation/q1/code/common/physics.py
implementation/q1/code/common/route.py
```

Q2 不得新增 `q2_physics.py`、`q2_dem.py` 或第二份能耗公式。Q2-B 才会在
`route_evaluator.py` 中调用 `common.route.leg_time` 与 `common.route.leg_energy`，
并对多点路线逐航段传递剩余载荷。

## 后续阶段门

1. Q2-B：实现并用人工小例子验收多点路线评价器；
2. Q2-C：实现 UAV/共享电池 CP-SAT 调度器和硬截止检查；
3. Q2-D：接入自适应 ALNS、访问顺序邻域和 Pareto archive；
4. Q2-E：独立事件仿真、方法比较、小规模精确验证和正式解冻结。

在 Q2-B/C 通过前，不生成正式路线、WTD、Cmax、能耗或 Pareto 结果。

## 运行 Q2-A 审计

```powershell
python implementation/q2/code/q2/audit_q2_a.py
```

正式求解入口暂时不执行优化；`run_q2.py` 会明确提示当前阶段状态。

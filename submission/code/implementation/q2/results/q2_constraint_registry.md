# Q2-A 约束登记表

本文档是 Q2 后续实现的单一约束登记表。`HARD` 必须在任何候选解中满足；
`DERIVED` 是由题面和 Q1 冻结物理推导出的计算关系；`MODELING CHOICE` 是需要
在论文中明确说明、但不应冒充题面硬约束的建模选择。

## HARD：不可违反约束

| 编号 | 约束 | 正式实现要求 |
| --- | --- | --- |
| H01 | 货箱不可拆分 | 一个 box ID 只能完整地属于一条 trip/一个 stop |
| H02 | 全覆盖且只覆盖一次 | 80 个 box ID 恰好各出现一次；缺失、重复、派生 ID 均失败 |
| H03 | 闭合路线 | 每个 trip 为 `O01 -> S_i -> ... -> S_j -> O01`，最终必须返回 O01 |
| H04 | 初始质量 | 起飞总质量 `sum(mass) <= Q_g`；后续只卸不装 |
| H05 | 初始体积 | 起飞总体积 `sum(volume) <= V_g` |
| H06 | 逐段能量 | 每一条有向航段调用 Q1 `leg_energy(g, from, to, payload)`；禁止总距离乘单一载荷 |
| H07 | 返航安全余量 | 闭合路线总能耗 `<= (1-rho_g) * Euse_g` |
| H08 | 实体运输无人机 | 只能使用数据中的 8 架 UAV，并满足 `trip.gtype == uid.gtype` |
| H09 | UAV 不重叠 | 同一实体 UAV 的任务占用区间不得重叠 |
| H10 | 同机型共享电池 | 电池只能服务相同机型；跨机型禁止混用 |
| H11 | 电池数量 | 使用的电池 ID 不超过 A=6、B=4、C=4 的台账数量 |
| H12 | 电池占用不重叠 | 同一电池的飞行区间和后续充电区间不得与下一次飞行/充电重叠 |
| H13 | SOC 规则 | 初次使用前 SOC=100%；再次使用前必须充至 100%；路线结束 SOC >= rho_g |
| H14 | 首批硬截止 | `delivery_time <= t_first` |
| H15 | 医疗硬截止 | 医疗物资 `delivery_time <= t_exp` |
| H16 | 双标签货箱 | 同时首批且医疗时，截止取 `min(t_first, t_exp)` |

## DERIVED：必须由模型计算的关系

| 编号 | 关系 | 计算口径 |
| --- | --- | --- |
| D01 | 逐站载荷下降 | `q(O01,S1)=总质量`；交付站点后从后续航段载荷中扣除本站质量 |
| D02 | 逐站送达偏移 | 从架次 start 起逐事件累加：准备/装载、每条飞行腿、每站 handover；前站 handover 必须进入后站偏移 |
| D03 | 送达定义 | 完成该服务区本批货箱交接的时刻，作为本站所有箱子的 delivery time |
| D04 | 多站能耗 | `sum(leg_energy(..., current_payload))`，不得使用 Q1 单点 `qmax` 代替 |
| D05 | 作业时长 | `t_prep + n_box*t_box_load + sum(leg_time) + sum(handover)` |
| D06 | 电池 SOC | `soc_after = 1 - route_energy/Euse`；充电时间由题目两阶段函数计算 |
| D07 | 资源解耦 | UAV 在返航后释放；电池在飞行结束后进入充电，UAV 与电池不永久绑定 |
| D08 | 完工时间 | `Cmax = max(return_time_s)`，以所有实体 UAV 最晚返航为准 |

## MODELING CHOICE：需要透明说明的选择

| 编号 | 选择 | 约束边界 |
| --- | --- | --- |
| M01 | 外层 ALNS + 内层 schedule decoder | ALNS 只搜索运输结构；UID、电池和时间交给解码子问题 |
| M02 | WTD 及时性指标 | 非硬截止的延误用 `sum(prio * max(0, delivery-t_exp))`；不能抵销 H14/H15 违例 |
| M03 | Pareto archive | 记录 `(WTD, Cmax, E_total, N_trip)` 非支配解，最后按透明规则选一套正式方案 |
| M04 | Q1 单站方案 | 仅作为同一 Q2 evaluator/decoder 下的 baseline 或 warm start，不固定为 Q2 任务 |
| M05 | 访问顺序邻域 | 2-opt、relocate、swap、reverse 可用于搜索；不能先用 TSP 顺序永久冻结 |
| M06 | 算子自适应 | 使用 ALNS package 或显式权重更新；不得继续所有邻域等概率永久抽样 |
| M07 | 多停靠点加速 | 任何 `max_stops` 只能用于初始化/候选加速，并须做放宽验证，不得写成正式硬约束 |

## 阶段门

- Q2-A：本登记表、数据审计、接口骨架；不产生正式解。
- Q2-B：逐段路线物理和人工小例子通过后，才允许路线候选生成。
- Q2-C：UAV/电池 CP-SAT 与硬截止通过后，才允许完整调度。
- Q2-D：自适应 ALNS、Pareto 和多 seed 才能运行。
- Q2-E：独立事件仿真与小规模精确验证通过后，才冻结 Q2 正式方案。

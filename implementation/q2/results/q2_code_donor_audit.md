# Q2-A 代码供体审计

本审计依据：

- GitHub `Cononln/cszd` 的 `origin/q1/q1-3-final`（Q1 正式公共层，当前本地可见提交 `c6a72dc`）；
- 本地 A/raw：`D题/D题实现代码/`；
- 本地 B/super：`D题/进阶版/`；
- Q2-A 提示词指定的三类论文方法。

结论是迁移正确结构和物理思想，不把任一供体原样提升为正式 Q2。仓库最终只保留
`implementation/q2/` 一套正式实现。

## 供体映射

| 模块 | 来源 | 处理 | 主要理由 |
| --- | --- | --- | --- |
| 数据、DEM、航段、能耗 | GitHub `implementation/q1/code/common/` | **KEEP** | Q1 已冻结；Q2 直接复用 `data.py`、`dem.py`、`physics.py`、`route.py`，不复制公式 |
| Q2 工程/Trip 骨架 | B `进阶版/code/q2/q2_model.py` | **MIGRATE** | 保留 Trip/资源解码的模块化方向；重写截止时间、送达偏移和最终接口 |
| Stage A/B 模式和精确装箱 | B `q2_main.py` | **REWRITE** | `max_size=3` 成为硬限制，模式代价未逐段计算多点能耗；只能作为候选构造参考 |
| B 版 ALNS | B `q2_main.py` | **REWRITE** | `rng.integers(0, 6)` 为永久等概率选择，不是自适应 ALNS；目标也未将医疗硬截止作为硬约束 |
| B 版 CP-SAT 调度 | B `q2_model.py::cp_schedule` | **MIGRATE** | UAV/电池 NoOverlap 结构可复用；需补医疗截止、独立事件校验和统一 start/depart 口径 |
| 访问顺序启发式 | B `common/route.py::tsp_order` | **REWRITE** | 仅按飞行时间预先选序；正式 Q2 必须把交接时间、动态载荷、能耗和硬截止纳入访问顺序搜索 |
| B `common/data.py`、`common/route.py`、`common/physics.py` | B 复制的公共层 | **REJECT** | 与 GitHub Q1 common 重复，易造成 DEM、字段和能耗口径分叉 |
| 多点路线评估 | A `D题实现代码/q2_common.py::evaluate_route` | **MIGRATE** | 已逐航段更新载荷、累计交接时间；必须改用 Q1 canonical 字段和 Q1 common 航段接口 |
| A 路线拆分/资源模拟 | A `q2_common.py::decode_group_to_routes/simulate_dispatch` | **REWRITE** | 旧字段、贪心资源派单，且 `MAX_STOPS=3` 是硬剪枝；后续改为 Q2-B/C 正式接口 |
| A NSGA-II | A `q2_1.py` | **MIGRATE** | 可作为全局箱级编码和 Pareto 记录的研究参考，不作为最终求解器 |
| A 贪心合并与预设扫描 | A `q2_2.py` | **MIGRATE** | 作为 legacy baseline 参考；必须和正式 route evaluator/decoder 共用 |
| A `hard_deadline` | A `q2_common.py::hard_deadline` | **REWRITE** | 思路正确但使用旧中文字段，且同时满足首批+医疗时只返回首批；现已在 `deadlines.py` 取两者最小值 |
| Adaptive ALNS engine | N-Wouda/ALNS package | **KEEP（后续依赖）** | Q2-A 仅登记依赖；Q2-D 直接使用公开 API，不复制整仓库 |
| Sacramento 2019 | 论文方法 | **KEEP（方法依据）** | destroy/repair、自适应权重、接受准则、局部搜索 |
| Poikonen & Golden 2020 | 论文方法 | **KEEP（方法依据）** | 多点访问、逐站卸货、载荷与能耗耦合 |
| Liu et al. 2025 | 论文方法 | **KEEP（方法依据）** | 路线外层搜索 + 有限共享电池调度子问题 |

## 已确认的 P0/P1 差距

1. B 版 `Trip.lateness`、`first_violation` 和 `cp_schedule` 只把 `first` 箱作为硬时限；医疗箱仍只进入软延误。正式口径应为首批截止和医疗期望送达均为硬截止。
2. B 版 `Trip.__init__` 计算后续站点 `offset` 时只累加飞行腿，未把前站 handover 加入后续送达时刻。A 版 `evaluate_route` 的逐事件累加思路可迁移。
3. A/B 都在不同程度上把最多 3 个停靠点写进正式搜索空间。题面没有该上限；后续最多只能作为初始化或加速参数，并做放宽验证。
4. B 版 Stage A 用服务区-物资类型汇总模式和代价代理，不能替代逐箱、多站、逐段能量的最终判定；Q1 的单站 `qmax` 不能直接筛掉 Q2 多站路线。
5. B 版 ALNS 所有邻域永久等概率；A 版是 NSGA-II 或贪心预设扫描。正式 Q2-D 必须建立自适应算子权重，并由同一 decoder 评价。
6. A/B 供体均没有 Q2-E 要求的独立逐事件 validator；现阶段只登记接口，不接受供体结果作为正式 Q2 结果。

## 当前处理边界

Q2-A 已建立 `models.py`、`deadlines.py` 及后续阶段 skeleton，并生成真实数据审计。
Q2-B 之前不运行路线优化，Q2-C 之前不运行资源调度，Q2-D 之前不接入 ALNS，
因此本轮没有生成任何 Q2 最优路线或结果文件。

# Q1-2 最大安全载荷求解与验收

## 1. 范围与数学定义

本阶段对每个机型 `g ∈ {A,B,C}` 和服务区 `s ∈ {S001,…,S015}`，只考虑单服务区任务
`O01 → s → O01`，求连续质量意义下的最大安全载荷：

`q_max(g,s) = max {q ∈ [0,Q_g] : E_trip(g,s,q) ≤ E_limit,g}`

其中：

`E_trip(g,s,q) = E_O01→s(g,q) + E_s→O01(g,0)`

`E_limit,g = (1-rho_g) E_g^use`

返程载荷严格固定为 `q=0`。本阶段的 `q_max` 是能量安全条件下的连续质量边界；货箱不可拆分、体积、需求和组批在 Q1-3 单独处理。

## 2. 文献依据与边界

- Cheng, Adulyasak & Rousseau (2020) 将非线性能耗直接纳入无人机任务可行性约束。本实现借鉴这一建模思想，将 `E_trip(q) ≤ E_limit` 作为硬边界，没有复现其完整路径模型、能耗函数或精确算法。
- Zhang et al. (2021) 说明配送无人机能耗随机型、载荷和运行假设变化。本实现分别读取 A/B/C 的赛题参数，不使用统一经验系数，也不以文献参数替换赛题的 `L0`、`LF`、`Q` 或电池参数。
- Masmoudi et al. (2022) 说明多包裹载荷状态会影响配送决策。本实现先求连续质量能力边界，后续再在 Q1-3 处理离散货箱质量、体积和组合。

赛题公式与赛题数据优先于文献；本阶段没有修改 Q1-1 冻结的公共物理模型。

## 3. 求解方法

1. 对每个组合在 `[0,Q_g]` 上取 101 个载荷点，检查 `E_trip(q)` 有限且单调不减。
2. 若 `E_trip(Q_g) ≤ E_limit`，直接判为 `RATED_CAPACITY`，令 `q_max=Q_g`。
3. 若空载可行而额定满载不可行，在 `[0,Q_g]` 上用连续二分求解 `E_trip(q_max)=E_limit`。
4. 对每个结果检查 `q_max` 可行性；对能量受限组合再检查 `q_max+δ`（`δ=0.001 kg`）越过能量上限。

二分停止条件为载荷区间宽度不超过 `1e-6 kg`，最多 80 次迭代；能量判定容差为 `1e-8 kWh`。

## 4. 总体结果

| 指标 | 数量 |
| --- | ---: |
| 总组合 | 45 |
| 额定容量可行 (`RATED_CAPACITY`) | 39 |
| 能量受限 (`ENERGY_LIMITED`) | 6 |
| 空载不可达 (`EMPTY_TRIP_INFEASIBLE`) | 0 |
| 能量曲线非递减 | 45/45 |
| q_max 可行 | 45/45 |

## 5. 六个能量受限组合

| 机型 | 服务区 | Q_g (kg) | q_max (kg) | q_max/Q_g | E_limit (kWh) | 裕量 (kWh) | q_max+δ 越界 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| C | S002 | 80.0 | 68.989855 | 0.86237318 | 6.400000000 | 0.000000009 | PASS |
| C | S003 | 80.0 | 68.282074 | 0.85352593 | 6.400000000 | 0.000000008 | PASS |
| C | S004 | 80.0 | 63.759460 | 0.79699325 | 6.400000000 | 0.000000001 | PASS |
| B | S008 | 30.0 | 28.869349 | 0.96231163 | 3.200000000 | 0.000000007 | PASS |
| C | S008 | 80.0 | 59.091416 | 0.73864270 | 6.400000000 | 0.000000008 | PASS |
| C | S012 | 80.0 | 68.191208 | 0.85239010 | 6.400000000 | 0.000000007 | PASS |

## 6. 45 组完整结果

| 机型 | 服务区 | Q (kg) | q_max (kg) | q_max/Q | 状态 | E(q_max) (kWh) | 裕量 (kWh) |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: |
| A | S001 | 25.0 | 25.000000 | 1.00000000 | RATED_CAPACITY | 1.317623297 | 2.282376703 |
| B | S001 | 30.0 | 30.000000 | 1.00000000 | RATED_CAPACITY | 1.278704186 | 1.921295814 |
| C | S001 | 80.0 | 80.000000 | 1.00000000 | RATED_CAPACITY | 3.086420443 | 3.313579557 |
| A | S002 | 25.0 | 25.000000 | 1.00000000 | RATED_CAPACITY | 3.086372244 | 0.513627756 |
| B | S002 | 30.0 | 30.000000 | 1.00000000 | RATED_CAPACITY | 2.994806163 | 0.205193837 |
| C | S002 | 80.0 | 68.989855 | 0.86237318 | ENERGY_LIMITED | 6.399999991 | 0.000000009 |
| A | S003 | 25.0 | 25.000000 | 1.00000000 | RATED_CAPACITY | 3.154405976 | 0.445594024 |
| B | S003 | 30.0 | 30.000000 | 1.00000000 | RATED_CAPACITY | 3.062054891 | 0.137945109 |
| C | S003 | 80.0 | 68.282074 | 0.85352593 | ENERGY_LIMITED | 6.399999992 | 0.000000008 |
| A | S004 | 25.0 | 25.000000 | 1.00000000 | RATED_CAPACITY | 3.266791437 | 0.333208563 |
| B | S004 | 30.0 | 30.000000 | 1.00000000 | RATED_CAPACITY | 3.169893093 | 0.030106907 |
| C | S004 | 80.0 | 63.759460 | 0.79699325 | ENERGY_LIMITED | 6.399999999 | 0.000000001 |
| A | S005 | 25.0 | 25.000000 | 1.00000000 | RATED_CAPACITY | 2.239696580 | 1.360303420 |
| B | S005 | 30.0 | 30.000000 | 1.00000000 | RATED_CAPACITY | 2.173244240 | 1.026755760 |
| C | S005 | 80.0 | 80.000000 | 1.00000000 | RATED_CAPACITY | 5.282231030 | 1.117768970 |
| A | S006 | 25.0 | 25.000000 | 1.00000000 | RATED_CAPACITY | 1.388963913 | 2.211036087 |
| B | S006 | 30.0 | 30.000000 | 1.00000000 | RATED_CAPACITY | 1.349324135 | 1.850675865 |
| C | S006 | 80.0 | 80.000000 | 1.00000000 | RATED_CAPACITY | 3.251603825 | 3.148396175 |
| A | S007 | 25.0 | 25.000000 | 1.00000000 | RATED_CAPACITY | 2.016320553 | 1.583679447 |
| B | S007 | 30.0 | 30.000000 | 1.00000000 | RATED_CAPACITY | 1.958211619 | 1.241788381 |
| C | S007 | 80.0 | 80.000000 | 1.00000000 | RATED_CAPACITY | 4.675754754 | 1.724245246 |
| A | S008 | 25.0 | 25.000000 | 1.00000000 | RATED_CAPACITY | 3.382218125 | 0.217781875 |
| B | S008 | 30.0 | 28.869349 | 0.96231163 | ENERGY_LIMITED | 3.199999993 | 0.000000007 |
| C | S008 | 80.0 | 59.091416 | 0.73864270 | ENERGY_LIMITED | 6.399999992 | 0.000000008 |
| A | S009 | 25.0 | 25.000000 | 1.00000000 | RATED_CAPACITY | 2.383193375 | 1.216806625 |
| B | S009 | 30.0 | 30.000000 | 1.00000000 | RATED_CAPACITY | 2.312828780 | 0.887171220 |
| C | S009 | 80.0 | 80.000000 | 1.00000000 | RATED_CAPACITY | 5.661244508 | 0.738755492 |
| A | S010 | 25.0 | 25.000000 | 1.00000000 | RATED_CAPACITY | 2.067548020 | 1.532451980 |
| B | S010 | 30.0 | 30.000000 | 1.00000000 | RATED_CAPACITY | 2.007953053 | 1.192046947 |
| C | S010 | 80.0 | 80.000000 | 1.00000000 | RATED_CAPACITY | 4.853335670 | 1.546664330 |
| A | S011 | 25.0 | 25.000000 | 1.00000000 | RATED_CAPACITY | 1.216695605 | 2.383304395 |
| B | S011 | 30.0 | 30.000000 | 1.00000000 | RATED_CAPACITY | 1.181108856 | 2.018891144 |
| C | S011 | 80.0 | 80.000000 | 1.00000000 | RATED_CAPACITY | 2.847635200 | 3.552364800 |
| A | S012 | 25.0 | 25.000000 | 1.00000000 | RATED_CAPACITY | 3.129342641 | 0.470657359 |
| B | S012 | 30.0 | 30.000000 | 1.00000000 | RATED_CAPACITY | 3.037128427 | 0.162871573 |
| C | S012 | 80.0 | 68.191208 | 0.85239010 | ENERGY_LIMITED | 6.399999993 | 0.000000007 |
| A | S013 | 25.0 | 25.000000 | 1.00000000 | RATED_CAPACITY | 2.072486864 | 1.527513136 |
| B | S013 | 30.0 | 30.000000 | 1.00000000 | RATED_CAPACITY | 2.012751596 | 1.187248404 |
| C | S013 | 80.0 | 80.000000 | 1.00000000 | RATED_CAPACITY | 4.887622990 | 1.512377010 |
| A | S014 | 25.0 | 25.000000 | 1.00000000 | RATED_CAPACITY | 2.424334567 | 1.175665433 |
| B | S014 | 30.0 | 30.000000 | 1.00000000 | RATED_CAPACITY | 2.354003833 | 0.845996167 |
| C | S014 | 80.0 | 80.000000 | 1.00000000 | RATED_CAPACITY | 5.604727548 | 0.795272452 |
| A | S015 | 25.0 | 25.000000 | 1.00000000 | RATED_CAPACITY | 2.616399658 | 0.983600342 |
| B | S015 | 30.0 | 30.000000 | 1.00000000 | RATED_CAPACITY | 2.541669082 | 0.658330918 |
| C | S015 | 80.0 | 80.000000 | 1.00000000 | RATED_CAPACITY | 6.126295009 | 0.273704991 |

## 7. 验收检查

| 检查项 | 结果 |
| --- | --- |
| total_pairs_is_45 | PASS |
| rated_capacity_pairs_is_39 | PASS |
| energy_limited_pairs_is_6 | PASS |
| energy_limited_pair_set_matches_q1_1 | PASS |
| empty_trip_infeasible_pairs_is_0 | PASS |
| no_invalid_energy_profiles | PASS |
| roundtrip_energy_nondecreasing_all | PASS |
| qmax_feasible_all | PASS |
| energy_limited_qmax_below_rated | PASS |
| energy_limited_boundary_active | PASS |
| energy_limited_boundary_residual_within_energy_tol | PASS |
| energy_limited_plus_delta_infeasible | PASS |
| qmax_values_in_range | PASS |
| all_checks_pass | PASS |

能量受限组合的最大边界残差 `max(abs(margin_at_qmax))`：`9.03195829238e-09 kWh`。

失败明细：

- 无

## 8. 参考文献

[1] Cheng C, Adulyasak Y, Rousseau L M. Drone routing with energy function: Formulation and exact algorithm. *Transportation Research Part B: Methodological*, 2020, 139: 364–387. DOI: 10.1016/j.trb.2020.06.011.

[2] Zhang J, Campbell J F, Sweeney D C, Hupman A C. Energy consumption models for delivery drones: A comparison and assessment. *Transportation Research Part D: Transport and Environment*, 2021, 90: 102668. DOI: 10.1016/j.trd.2020.102668.

[3] Masmoudi M A, Mancini S, Baldacci R, Kuo Y H. Vehicle routing problems with drones equipped with multi-package payload compartments. *Transportation Research Part E: Logistics and Transportation Review*, 2022, 164: 102757. DOI: 10.1016/j.tre.2022.102757.

## 9. 阶段结论

**PASS：可以冻结 Q1-2**

若本报告为 PASS，下一阶段等待确认后进入 Q1-3：真实货箱离散组批、机型选择与 Q1 正式优化。

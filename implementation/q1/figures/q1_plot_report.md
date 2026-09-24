# Q1 统一出图报告

## 数据锁定
- 绘图入口：`implementation/q1/code/q1/plot_q1_results.py`
- 读取目录：`implementation/q1/results/`（仅读）
- Q1 状态：`PASS`；货箱：80；正式架次：18
- Formal：59.0829 kWh，32804.1 s
- Baseline：64.1967 kWh，33054.9 s
- 求解器：45/45 OPTIMAL
- 结果文件哈希前后相同：`YES`

## Figure contract
- 核心结论：在冻结的物理约束和 q_max 边界下，Formal 方案以理论下界 18 架次完成全部 80 箱，并在相同架次下降低总能耗与累计作业时间。
- 图组原型：quantitative grid；主证据为物理包络、q_max、组批利用率和 Formal/Baseline 三目标比较，补充证据为鲁棒性与求解器审计。
- Backend：Python / Matplotlib；PDF/SVG 保留矢量文字，PNG 为 600 dpi 预览。
- 统计说明：本组为确定性优化结果，不含重复实验或误差条；所有数量和单位直接来自 CSV/JSON。

## 生成图
- `Fig_Q1_01_capacity_map`（main）：三种机型在 15 个服务区的最大安全载荷、能耗利用率与能量约束激活位置；数据：implementation/q1/results/q1_capacity.csv
- `Fig_Q1_02_flight_envelope`（main）：载荷相关等效航程的审计点与 O01—服务区单程距离安全包络；数据：implementation/q1/results/q1_physics_audit.csv;implementation/q1/results/q1_physics_energy_checks.csv
- `Fig_Q1_03_batch_plan`（main）：正式架次机型构成与质量/体积双容量利用率；数据：implementation/q1/results/q1_solution_trips.csv
- `Fig_Q1_04_service_allocation`（main）：15 个服务区的正式架次载荷构成与机型配置；正式架次达到理论下界；数据：implementation/q1/results/q1_service_summary.csv
- `Fig_Q1_05_method_comparison`（main）：Baseline 与 Formal 在架次、总能耗和累计作业时间上的三目标比较；数据：implementation/q1/results/q1_method_comparison.csv
- `Fig_Q1_06_utilization_tradeoff`（main）：18 个正式架次的质量与体积利用率及容量边界；数据：implementation/q1/results/q1_solution_trips.csv
- `Fig_Q1_07_energy_margin`（main）：18 个正式架次的单架次能量安全余量排序；数据：implementation/q1/results/q1_solution_trips.csv
- `Fig_Q1_08_service_tradeoff`（main）：服务区级累计作业时间、运输能耗与货物质量的关系；数据：implementation/q1/results/q1_service_summary.csv
- `Fig_Q1_09_sensitivity`（main）：返航安全边界收紧下固定正式方案的违例架次敏感性；数据：implementation/q1/results/q1_final.json
- `Fig_Q1_10_lexicographic_stages`（main）：严格词典序 L1→L2→L3 的能耗与累计作业时间变化；数据：implementation/q1/results/q1_lexicographic_stages.csv
- `Fig_Q1_S1_solver_audit`（supplement）：15 个服务区 × 3 个词典序阶段的求解器最优性审计；数据：implementation/q1/results/q1_solver_status.csv
- `Fig_Q1_S2_solver_cost`（supplement）：候选批次数量与三阶段求解时间的关系；数据：implementation/q1/results/q1_solver_status.csv

## 数据映射说明
- 图形采用结构化适配：绝对 qmax、能耗利用率、正式架次载荷和物理审计字段均直接映射到当前锁定结果列。

## QA
- 每张多面板图均执行 1.5 pt panel-alignment gate。
- 每张 PDF 均执行 PDF 文本字号（≥5 pt）审计和 rendered collision audit。
- QA 阻断项：`无`
- 冻结结果文件在生成前后的哈希一致性已验证。

## 结论
- PASS：Q1 绘图完成，可进入论文结果撰写

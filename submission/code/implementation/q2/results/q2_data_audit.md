# Q2-A 数据审计

- 状态：**PASS**
- 正式优化：未运行（符合 Q2-A 阶段门）
- 货箱：80 箱；服务区：15 个；
首批保障箱：30；医疗物资箱：16；
同时属于两类：15；硬截止箱：31
- 运输无人机：8 架，按机型 {'A': 4, 'B': 2, 'C': 2}
- 共享电池：A: 6 组, 满充 1800s; B: 4 组, 满充 2400s; C: 4 组, 满充 3000s
- 首批截止范围：3600.0–10800.0 s
- 期望送达范围：3600.0–18000.0 s
- 统一硬截止范围：3600.0–10800.0 s
- 优先系数范围：4.0–24.0，均值 11.950

## 数据检查

- PASS: `n_boxes_is_80`
- PASS: `n_service_areas_is_15`
- PASS: `fleet_is_8`
- PASS: `fleet_types_are_abc`
- PASS: `all_boxes_have_expected_time`
- PASS: `all_hard_boxes_have_hard_deadline`

## 口径说明

- 15 boxes are both first-batch and medical; hard_deadline takes min(t_first, t_exp).
- Q2 multi-stop energy and delivery offsets are not evaluated in Q2-A.
- No Q2 final route, WTD, Cmax, energy or Pareto result is produced in Q2-A.

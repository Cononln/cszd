# -*- coding: utf-8 -*-
"""
2026年研究生数学建模竞赛 D题 —— 问题三 · 方法2：贪心构造 + 中继覆盖分配 + 派单预设扫描（q3_2）

范围：承接 q2_2.py 的"简单可解释构造式基线"路线——第一阶段(单站集合划分->
贪心多站合并)与q2_2.py完全一致，直接从q2_2.py只读import(baseline_cost/
route_from_areas/arrival_absolute_safe/try_merge/greedy_merge_routes/
priority_balanced/priority_urgency/priority_energy/PRESETS/fig_preset_compare)，
不重复设计——路线构造与三套派单哲学同通信维度完全正交。

在q2_2的路线集合固定住之后，新增两件事：
  1. 中继需求解析：对每条合并后路线调用q3_common.attach_relay_requirements，
     结果是确定性的(只看路线几何+通信画像，不依赖派单顺序)，与NSGA-II版本(q3_1)
     算出来的应该是同一套windows——这也是本方法能对照验证的地方。
  2. 中继分配报告：simulate_joint_dispatch内部才是真正决定"哪个中继架次落在
     哪个时间点"的地方(依赖实际起飞时刻，路线级的windows只是相对时间，脱离
     实际调度无法真正排EDF)，所以q3_2_relay_assignment.csv不是一个独立于
     仿真之外的预排班表，而是仿真跑完后从route.relay_req + sim.relay_sorties
     做的一次joins式复盘报告——诚实展示每条路线的通信需求是否被覆盖、被哪架
     中继机身在什么时刻服务，排不下的窗口直接标"缺口"，不静默丢弃(呼应q2_2.py
     对硬约束违反数"如实报告不当bug"的既有写法习惯)。

三组派单预设扫描把simulate_dispatch/compute_objectives替换成
simulate_joint_dispatch/compute_objectives_joint，循环结构不变；
fig_preset_compare原样复用，因为compute_objectives_joint返回的仍是
f1_及时性/f2_makespan_s/f3_总能耗_kWh/f4_架次数/violations这套通用key。

关键建模假设清单见 q3_common.MODELING_ASSUMPTIONS。

运行方式：
    python q3_2.py
输出（当前目录 / figures/）：
    q3_2_routes.csv            合并后的路线明细（+通信保障方式列）
    q3_2_relay_assignment.csv  中继需求 x 实际中继架次 复盘报告
    q3_2_sorties.csv           主预设的运输架次-无人机-电池-起止时间
    q3_2_relay_sorties.csv     主预设的中继架次明细
    q3_2_box_delivery.csv      主预设的逐箱送达时刻
    q3_2_resource_timeline.csv 主预设的资源时间轴(运输+中继合并)
    q3_2_preset_compare.csv    3组预设的 f1-f4 + 违反数对比表
    q3_2_summary.txt           结果汇总+建模假设清单+校验+对照q2_2/q3_1
    figures/q3_2_01_路线结构与通信覆盖图.png
    figures/q3_2_02_地形遮挡剖面示例.png
    figures/q3_2_03_联合资源甘特图.png
    figures/q3_2_04_优先级权衡对比.png
    figures/q3_2_05_机队架次能耗对比.png
"""
import os
import time

import numpy as np
import pandas as pd

from q00 import load_transport_drone, load_relay_drone
from q1_2_common import load_base_data, enumerate_candidates, solve_set_partitioning, total_metrics, validate_selection
from q2_common import MAX_STOPS, load_leg_geometry_table, build_box_index, hard_deadline
from q2_2 import (
    baseline_cost, route_from_areas, greedy_merge_routes,
    priority_balanced, priority_urgency, priority_energy, PRESETS, fig_preset_compare,
)
from q3_common import (
    MODELING_ASSUMPTIONS, load_comm_constants, gw_position, load_dem_full, build_node_positions,
    load_or_build_relay_layer, attach_relay_requirements, simulate_joint_dispatch,
    compute_objectives_joint, fig_comm_coverage_map, fig_terrain_los_profile,
    fig_joint_resource_gantt, fig_fleet_breakdown,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

Q2_2_BASELINE = dict(f4=16, f3=58.179, f1=200895.0, f2=10173.7, violations=5)
Q2_1_BASELINE = dict(f4=29, f3=82.777, violations=0)


def relay_desc(route, relay_candidates):
    req = route["relay_req"]
    if not req["windows"]:
        return "直连" if req["feasible"] else "缺口(无覆盖候选)"
    parts = []
    for w in req["windows"]:
        c = relay_candidates[w["candidate_id"]]
        parts.append(f"({c['lon']:.5f},{c['lat']:.5f},AGL{c['agl']:.0f}m)")
    tag = "中继" + ",".join(parts)
    if not req["feasible"]:
        tag += "+缺口"
    return tag


def pick_worst_gap_leg(comm_profile, phase_coverage, leg_geo):
    """给fig_terrain_los_profile自动挑示例腿：优先挑'有实际覆盖候选'的相位里
    遮挡最严重(blocked_points最多)的一条,而不是零覆盖的硬缺口——后者没有
    candidate可画第二段视线,图会缺一半信息;零覆盖硬缺口已经在summary里单独
    如实报告,不需要靠这张图承担。"""
    best = None  # (n_blocked, a, b, phase_name, candidate_id)
    for (a, b), phases in comm_profile.items():
        for phase_name, ph in phases.items():
            if not ph["needs_relay"]:
                continue
            covering = phase_coverage.get((a, b, phase_name), [])
            if not covering:
                continue
            n_blocked = len(ph["blocked_points"])
            if best is None or n_blocked > best[0]:
                best = (n_blocked, a, b, phase_name, covering[0])
    return best


# ---------------------------------------------------------------------------
# 主程序
# ---------------------------------------------------------------------------
def main():
    leg_geo, o01, services = load_leg_geometry_table()
    boxes_df, spec_df, qmax_lookup, geo_table = load_base_data()
    _, fleet_df, battery_df = load_transport_drone()
    relay_spec_df, relay_fleet_df, relay_stock_df = load_relay_drone()
    relay_spec_row = relay_spec_df.iloc[0]
    box_index = build_box_index(boxes_df)

    print(f"[规模] 箱子数={len(boxes_df)}  服务区数={boxes_df['服务区编号'].nunique()}  机型数={len(spec_df)}")

    # -------------------- 1. 基线构造（问题一单站集合划分，同q2_2） --------------------
    candidates = enumerate_candidates(boxes_df, spec_df, geo_table, qmax_lookup)
    cost = baseline_cost(candidates, boxes_df)
    selected = candidates.iloc[solve_set_partitioning(candidates, boxes_df, cost)].reset_index(drop=True)
    N0, E0, T0 = total_metrics(selected)
    ok0, msg0 = validate_selection(selected, boxes_df)
    print(f"[基线] {msg0}")
    print(f"[基线] N0={N0}  E0={E0:.3f} kWh  T0={T0:.1f} s")
    if not ok0:
        raise RuntimeError("问题一单站基线覆盖校验失败,不应该发生: " + msg0)

    base_routes = []
    for _, row in selected.iterrows():
        sa = row["服务区编号"]
        box_rows = [box_index[bid] for bid in row["货箱列表"]]
        r = route_from_areas([sa], {sa: box_rows}, spec_df, leg_geo)
        if r is None:
            raise RuntimeError(f"单站批次 {sa} 转换失败——问题一已保证单站可行，不应该发生")
        base_routes.append(r)
    e_base_sum = sum(r["E_route_kWh"] for r in base_routes)
    print(f"[转换] 单站路线数={len(base_routes)}  总能耗={e_base_sum:.3f} kWh（对照基线E0={E0:.3f} kWh）")

    # -------------------- 2. 贪心多站合并（同q2_2） --------------------
    merge_log = []
    merged_routes = greedy_merge_routes(base_routes, spec_df, leg_geo, log=merge_log)
    e_merged_sum = sum(r["E_route_kWh"] for r in merged_routes)
    n_pair = sum(1 for m in merge_log if m["n_inputs"] == 2)
    n_triple = sum(1 for m in merge_log if m["n_inputs"] == 3)
    saving_pct = (e_base_sum - e_merged_sum) / e_base_sum * 100 if e_base_sum > 0 else 0.0
    print(f"[合并] 合并轮数={len(merge_log)}（两两={n_pair} 三合一={n_triple}）  "
          f"架次数 {len(base_routes)} -> {len(merged_routes)}  能耗 {e_base_sum:.3f} -> {e_merged_sum:.3f} kWh"
          f"（节省{saving_pct:.1f}%）")

    all_box_ids = [b["货箱编号"] for r in merged_routes for bs in r["boxes_by_stop"].values() for b in bs]
    ok_cov = len(all_box_ids) == len(boxes_df) and len(set(all_box_ids)) == len(boxes_df)
    print(f"[合并后覆盖校验] 覆盖{len(all_box_ids)}/{len(boxes_df)}箱,去重后{len(set(all_box_ids))}箱 -> "
          f"{'通过' if ok_cov else '失败'}")
    if not ok_cov:
        raise RuntimeError("合并后箱子覆盖校验失败")

    # -------------------- 3. 通信/中继全局预计算 + 路线级需求解析 --------------------
    t_pre = time.time()
    comm = load_comm_constants()
    gw_pos = gw_position(comm, o01)
    dem_arr, dem_transform, dem_bounds = load_dem_full()
    node_lonlat, node_work_elev, node_ground_elev = build_node_positions(o01, services)
    comm_profile, relay_candidates, phase_coverage = load_or_build_relay_layer(
        leg_geo, node_lonlat, node_work_elev, comm, gw_pos, dem_arr, dem_transform, dem_bounds,
        float(relay_spec_row["最大悬停离地高度"]), use_cache=True)
    n_phase_need = sum(1 for v in comm_profile.values() for p in v.values() if p["needs_relay"])
    n_gap_phase = sum(1 for v in phase_coverage.values() if len(v) == 0)
    print(f"[通信预计算] 需中继相位={n_phase_need}/{3 * len(comm_profile)}  中继候选点={len(relay_candidates)}  "
          f"零候选硬缺口相位={n_gap_phase}  用时={time.time() - t_pre:.1f}s")

    attach_relay_requirements(merged_routes, leg_geo, comm_profile, phase_coverage, spec_df)
    n_direct = sum(1 for r in merged_routes if not r["relay_req"]["windows"])
    n_relay_ok = sum(1 for r in merged_routes if r["relay_req"]["windows"] and r["relay_req"]["feasible"])
    n_relay_gap = sum(1 for r in merged_routes if not r["relay_req"]["feasible"])
    print(f"[中继需求解析] {len(merged_routes)}条路线中 直连={n_direct}  中继覆盖={n_relay_ok}  中继缺口={n_relay_gap}")

    # -------------------- 4. 三组派单优先级预设扫描（联合仿真） --------------------
    preset_results = {}
    for name, fn in PRESETS:
        sim = simulate_joint_dispatch(merged_routes, fleet_df, battery_df, spec_df,
                                       relay_fleet_df, relay_stock_df, relay_spec_row,
                                       relay_candidates, o01, fn)
        obj = compute_objectives_joint(sim, boxes_df)
        preset_results[name] = dict(sim=sim, obj=obj)
        print(f"[预设:{name}] f1={obj['f1_及时性']:.1f}  f2={obj['f2_makespan_s']:.1f}s  "
              f"f3={obj['f3_总能耗_kWh']:.3f}kWh  f4={obj['f4_架次数']}  违反数={len(obj['violations'])}")

    def violations(name):
        return len(preset_results[name]["obj"]["violations"])

    best_v = min(violations(n) for n, _ in PRESETS)
    tied = [n for n, _ in PRESETS if violations(n) == best_v]
    main_name = "均衡" if "均衡" in tied else tied[0]
    main_sim = preset_results[main_name]["sim"]
    main_obj = preset_results[main_name]["obj"]
    print(f"[主方案] 选择预设={main_name}（违反数最少,并列时优先均衡）")

    chosen_ids = sorted(set(w["candidate_id"] for r in merged_routes for w in r["relay_req"]["windows"]))
    chosen_relay = [relay_candidates[i] for i in chosen_ids]

    # -------------------- 输出 CSV --------------------
    route_rows = []
    for i, r in enumerate(merged_routes):
        route_rows.append(dict(
            路线编号=f"R{i + 1:03d}", 机型编号=r["机型编号"], 停靠序列="->".join(["O01"] + list(r["stops"]) + ["O01"]),
            箱数=r["n_box"], 总质量_kg=r["total_mass_kg"], 总体积_m3=r["total_vol_m3"],
            E_route_kWh=r["E_route_kWh"], T_route_s=r["T_route_s"],
            通信保障方式=relay_desc(r, relay_candidates),
            货箱列表="|".join(b["货箱编号"] for bs in r["boxes_by_stop"].values() for b in bs),
        ))
    pd.DataFrame(route_rows).to_csv(os.path.join(BASE_DIR, "q3_2_routes.csv"), index=False, encoding="utf-8-sig")

    relay_sorties_by_route = {}
    for rs in main_sim["relay_sorties"]:
        relay_sorties_by_route.setdefault(id(rs["route"]), []).append(rs)

    assign_rows = []
    for i, r in enumerate(merged_routes):
        req = r["relay_req"]
        served = relay_sorties_by_route.get(id(r), [])
        if not req["windows"]:
            assign_rows.append(dict(路线编号=f"R{i + 1:03d}", 通信保障方式="直连",
                                     需求候选位置数=0, 相对时间窗="-", 实际服务架次="-",
                                     实际中继无人机="-", 是否缺口=False))
            continue
        window_desc = "; ".join(f"cand#{w['candidate_id']}[{w['t_start']:.0f}s-{w['t_end']:.0f}s]"
                                 for w in req["windows"])
        served_desc = "; ".join(f"{rs['无人机编号']}@[{rs['service_start']:.0f}s-{rs['service_end']:.0f}s]"
                                 for rs in served) if served else "-"
        drones_desc = ",".join(sorted(set(rs["无人机编号"] for rs in served))) if served else "-"
        assign_rows.append(dict(
            路线编号=f"R{i + 1:03d}", 通信保障方式=("中继" if req["feasible"] else "中继+缺口"),
            需求候选位置数=len(req["windows"]), 相对时间窗=window_desc, 实际服务架次=served_desc,
            实际中继无人机=drones_desc, 是否缺口=(not req["feasible"]),
        ))
    pd.DataFrame(assign_rows).to_csv(
        os.path.join(BASE_DIR, "q3_2_relay_assignment.csv"), index=False, encoding="utf-8-sig")

    sortie_rows = [dict(架次编号=f"T{i + 1:03d}", 机型编号=s["机型编号"], 无人机编号=s["无人机编号"],
                         电池编号=s["电池编号"], 起飞时刻_s=s["start"], 返航时刻_s=s["end"],
                         停靠序列="->".join(["O01"] + list(s["route"]["stops"]) + ["O01"]))
                    for i, s in enumerate(main_sim["sorties"])]
    pd.DataFrame(sortie_rows).sort_values("起飞时刻_s").to_csv(
        os.path.join(BASE_DIR, "q3_2_sorties.csv"), index=False, encoding="utf-8-sig")

    relay_sortie_rows = [dict(
        架次编号=f"RT{i + 1:03d}", 无人机编号=rs["无人机编号"], 能源组件编号=rs["能源组件编号"],
        关联路线机型=rs["route"]["机型编号"], 关联路线停靠="->".join(["O01"] + list(rs["route"]["stops"]) + ["O01"]),
        悬停经度=rs["candidate"]["lon"], 悬停纬度=rs["candidate"]["lat"], 悬停AGL_m=rs["candidate"]["agl"],
        起飞时刻_s=rs["depart"], 到位时刻_s=rs["service_start"], 撤离时刻_s=rs["service_end"],
        返航时刻_s=rs["ground_arrive"], E_kWh=rs["E_kWh"], 电量是否达标=rs["energy_ok"],
    ) for i, rs in enumerate(main_sim["relay_sorties"])]
    pd.DataFrame(relay_sortie_rows).to_csv(
        os.path.join(BASE_DIR, "q3_2_relay_sorties.csv"), index=False, encoding="utf-8-sig")

    hd_map = {b["货箱编号"]: hard_deadline(b) for _, b in boxes_df.iterrows()}
    delivery_rows = []
    for _, b in boxes_df.iterrows():
        bid = b["货箱编号"]
        arrive = main_sim["box_delivery"].get(bid)
        delivery_rows.append(dict(货箱编号=bid, 服务区编号=b["服务区编号"], 物资类型=b["物资类型"],
                                   期望送达时间_s=b["期望送达时间"], 硬约束时限_s=hd_map[bid],
                                   实际送达时刻_s=arrive,
                                   是否硬约束超时=bool(hd_map[bid] is not None and arrive is not None
                                                     and arrive > hd_map[bid] + 1e-6)))
    pd.DataFrame(delivery_rows).to_csv(
        os.path.join(BASE_DIR, "q3_2_box_delivery.csv"), index=False, encoding="utf-8-sig")

    timeline_rows = []
    for ev in main_sim["drone_events"]:
        timeline_rows.append(dict(资源编号=ev["资源编号"], 资源类型="运输无人机", 事件类型=ev["类型"],
                                   开始_s=ev["start"], 结束_s=ev["end"]))
    for ev in main_sim["batt_events"]:
        timeline_rows.append(dict(资源编号=ev["资源编号"], 资源类型="运输电池", 事件类型=ev["类型"],
                                   开始_s=ev["start"], 结束_s=ev["end"]))
    for ev in main_sim["relay_events"]:
        timeline_rows.append(dict(资源编号=ev["资源编号"], 资源类型="中继无人机", 事件类型=ev["类型"],
                                   开始_s=ev["start"], 结束_s=ev["end"]))
    for ev in main_sim["relay_batt_events"]:
        timeline_rows.append(dict(资源编号=ev["资源编号"], 资源类型="中继能源组件", 事件类型=ev["类型"],
                                   开始_s=ev["start"], 结束_s=ev["end"]))
    pd.DataFrame(timeline_rows).sort_values(["资源编号", "开始_s"]).to_csv(
        os.path.join(BASE_DIR, "q3_2_resource_timeline.csv"), index=False, encoding="utf-8-sig")

    compare_rows = [dict(预设名称=n, f1_及时性=preset_results[n]["obj"]["f1_及时性"],
                          f2_makespan_s=preset_results[n]["obj"]["f2_makespan_s"],
                          f3_总能耗_kWh=preset_results[n]["obj"]["f3_总能耗_kWh"],
                          f4_架次数=preset_results[n]["obj"]["f4_架次数"],
                          硬约束违反数=len(preset_results[n]["obj"]["violations"]),
                          是否主方案=(n == main_name)) for n, _ in PRESETS]
    pd.DataFrame(compare_rows).to_csv(
        os.path.join(BASE_DIR, "q3_2_preset_compare.csv"), index=False, encoding="utf-8-sig")
    print("[saved] q3_2_routes.csv / q3_2_relay_assignment.csv / q3_2_sorties.csv / q3_2_relay_sorties.csv / "
          "q3_2_box_delivery.csv / q3_2_resource_timeline.csv / q3_2_preset_compare.csv")

    # -------------------- 图 --------------------
    fig_comm_coverage_map(comm_profile, phase_coverage, node_lonlat, o01, services, chosen_relay,
                           "q3_2_01_路线结构与通信覆盖图.png",
                           f"图q3.2-1  问题三 · 贪心构造+合并：通信保障方式分布（N={len(merged_routes)}架次）")

    worst = pick_worst_gap_leg(comm_profile, phase_coverage, leg_geo)
    if worst is not None:
        n_blocked, a, b, phase_name, cand_id = worst
        fig_terrain_los_profile(a, b, node_lonlat, node_work_elev, leg_geo, dem_arr, dem_transform,
                                 gw_pos, relay_candidates[cand_id], "q3_2_02_地形遮挡剖面示例.png",
                                 f"图q3.2-2  问题三 · 地形遮挡剖面示例（{a}->{b} {phase_name}段，"
                                 f"{n_blocked}个采样点被遮挡）")
    else:
        print("[警告] 未找到任何'有覆盖候选的需中继相位'，跳过图02")

    fig_joint_resource_gantt(main_sim, fleet_df, battery_df, relay_fleet_df, relay_stock_df,
                              "q3_2_03_联合资源甘特图.png",
                              f"图q3.2-3  问题三 · 贪心构造+合并（{main_name}预设）：运输+中继联合资源时间轴")
    fig_preset_compare(preset_results, main_name, "q3_2_04_优先级权衡对比.png",
                        "图q3.2-4  问题三 · 三组派单优先级预设的四目标权衡对比（含通信/中继约束）")
    fig_fleet_breakdown(main_obj, "q3_2_05_机队架次能耗对比.png",
                         f"图q3.2-5  问题三 · 主方案（{main_name}预设）：运输 vs 中继 架次数/能耗对比")

    # -------------------- summary --------------------
    multi_stop = sum(1 for r in merged_routes if len(r["stops"]) > 1)
    n_covered = sum(1 for v in delivery_rows if v["实际送达时刻_s"] is not None)

    lines = []
    lines.append("问题三 · 方法2：贪心构造 + 中继覆盖分配 + 派单预设扫描 —— 结果汇总")
    lines.append("=" * 60)
    lines.append("")
    lines.append("零、关键建模假设清单（附录3未给出可执行文字算法/公式时的合理默认，非题目原文）")
    for i, a_ in enumerate(MODELING_ASSUMPTIONS, 1):
        lines.append(f"  {i}. {a_}")
    lines.append("")
    lines.append(f"通信/中继全局预计算：需中继相位={n_phase_need}/{3 * len(comm_profile)}，"
                 f"中继候选点={len(relay_candidates)}个，零候选硬缺口相位={n_gap_phase}个，用时={time.time() - t_pre:.1f}s")
    lines.append("")
    lines.append("一、基线构造（问题一单站集合划分,均衡权重，同q2_2.py）")
    lines.append(f"  {msg0}")
    lines.append(f"  N0={N0}  E0={E0:.3f} kWh  T0={T0:.1f} s")
    lines.append("")
    lines.append("二、贪心多站合并（同q2_2.py，与通信/中继无关）")
    lines.append(f"  合并轮数={len(merge_log)}（两两合并{n_pair}次,三合一{n_triple}次）")
    lines.append(f"  架次数：{len(base_routes)} -> {len(merged_routes)}（其中多停靠架次{multi_stop}个，"
                 f"占比{multi_stop / max(len(merged_routes), 1) * 100:.1f}%）")
    lines.append(f"  总能耗（不含中继）：{e_base_sum:.3f} -> {e_merged_sum:.3f} kWh（节省{saving_pct:.1f}%）")
    lines.append(f"  合并后箱子覆盖：{len(all_box_ids)}/{len(boxes_df)}箱，去重后{len(set(all_box_ids))}箱 -> "
                 f"{'通过' if ok_cov else '失败'}")
    lines.append("")
    lines.append(f"三、通信保障方式分布：{len(merged_routes)}条路线中 直连={n_direct}  中继覆盖={n_relay_ok}  "
                 f"中继缺口={n_relay_gap}")
    if n_relay_gap > 0:
        lines.append(f"  [如实报告] {n_relay_gap}条路线的通信需求超出2个中继位置的可归并上限，或落在零候选")
        lines.append("  的硬缺口相位上，已计入violations的'通信保障缺口'条目并写入q3_2_relay_assignment.csv，")
        lines.append("  未被静默隐藏或强行凑单一中继覆盖。")
    lines.append("")
    lines.append("四、三组派单优先级预设对比（联合仿真：运输+中继）")
    for n, _ in PRESETS:
        obj = preset_results[n]["obj"]
        mark = "  <- 主方案" if n == main_name else ""
        lines.append(f"  [{n}] f1={obj['f1_及时性']:.1f}  f2={obj['f2_makespan_s']:.1f}s"
                     f"({obj['f2_makespan_s'] / 3600:.2f}h)  f3={obj['f3_总能耗_kWh']:.3f}kWh"
                     f"(运输{obj['f3_运输_kWh']:.3f}+中继{obj['f3_中继_kWh']:.3f})  "
                     f"f4={obj['f4_架次数']}(运输{obj['f4_运输架次']}+中继{obj['f4_中继架次']})  "
                     f"违反数={len(obj['violations'])}{mark}")
    lines.append("  主方案选择理由：违反数最少（并列时优先均衡）")
    lines.append("")
    lines.append("五、与q2_2（不建模通信/中继）及q2_1对照")
    lines.append(f"  q2_2(贪心基线,不建模通信)：架次数={Q2_2_BASELINE['f4']}，总能耗={Q2_2_BASELINE['f3']}kWh，"
                 f"硬约束违反数={Q2_2_BASELINE['violations']}")
    lines.append(f"  q2_1(NSGA-II全局解,不建模通信)：架次数={Q2_1_BASELINE['f4']}，总能耗={Q2_1_BASELINE['f3']}kWh，"
                 f"硬约束违反数={Q2_1_BASELINE['violations']}")
    lines.append(f"  q3_2(本方案,{main_name}预设)：架次数={main_obj['f4_架次数']}"
                 f"(运输{main_obj['f4_运输架次']}+中继{main_obj['f4_中继架次']})，"
                 f"总能耗={main_obj['f3_总能耗_kWh']:.3f}kWh"
                 f"(运输{main_obj['f3_运输_kWh']:.3f}+中继{main_obj['f3_中继_kWh']:.3f})，"
                 f"硬约束违反数={len(main_obj['violations'])}")
    lines.append("  q3_2的总能耗/架次数均应不低于q2_2的对应运输分量——叠加通信保障后必须额外派遣")
    lines.append("  中继架次、消耗额外能量，是约束变严格带来的合理代价，不是回归或bug。")
    lines.append("  另可与q3_1.py（NSGA-II全局联合优化）的结果对照，见q3_1_summary.txt——两者路线构造")
    lines.append("  方法不同但共享同一套通信画像/中继候选/联合仿真引擎(q3_common.py)，架次数量级可比，")
    lines.append("  不做跨脚本优劣裁决。")
    lines.append("")
    lines.append(f"六、覆盖校验：送达{n_covered}/{len(boxes_df)}箱（贪心合并结构性保证覆盖，"
                 f"通信不可行只记violation,不剔除路线）")
    lines.append("")
    lines.append("七、范围裁剪说明")
    lines.append(f"  单架次最多{MAX_STOPS}个停靠服务区；中继悬停位置为离散候选网格搜索结果，非连续优化")
    lines.append("  (见建模假设5)；中继资源分配的最终裁决在simulate_joint_dispatch内完成"
                 "(依赖实际起飞时刻)，")
    lines.append("  q3_2_relay_assignment.csv是仿真跑完后对路线需求与实际服务架次的复盘报告，不是独立")
    lines.append("  于仿真之外的预排班算法——路线级windows脱离实际起飞时刻无法真正做EDF排序。")

    with open(os.path.join(BASE_DIR, "q3_2_summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("[saved] q3_2_summary.txt")

    ok = ok0 and ok_cov and n_covered == len(boxes_df)
    print("[done] all checks passed" if ok else "[warn] some checks failed")


if __name__ == "__main__":
    main()

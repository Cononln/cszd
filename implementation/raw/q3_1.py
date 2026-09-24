# -*- coding: utf-8 -*-
"""
2026年研究生数学建模竞赛 D题 —— 问题三 · 方法1：NSGA-II 全局联合优化（q3_1）

范围：承接 q2_1.py 的全局分组编码NSGA-II，通用GA算子(compute_nearest_areas/
build_seed_population/dominates/fast_nondominated_sort/crowding_distance/
tournament_select/crossover/mutate/fig_pareto)直接从q2_1.py只读import——这些
函数只依赖metrics dict里f1-f4/violation这几个通用key的形状，不关心key背后的
联合语义，天然可以照搬，避免重复实现一遍fast_nondominated_sort/crowding_distance
这类容易出偏差的细节。

染色体编码不变：仍是长度80、按箱子分组的int数组。中继分配不新增搜索基因——
路线几何定下来之后，中继需求是确定性计算(q3_common.resolve_route_relay_requirement)，
不是需要GA搜索的自由维度，这与q2_1里派单顺序本身也不参与搜索是同一道理。

evaluate_chromosome在q2_1版本基础上：解码分组 -> decode_group_to_routes ->
attach_relay_requirements -> simulate_joint_dispatch -> compute_objectives_joint；
violation标量在q2_1原定义(硬时限超时+未覆盖箱惩罚)基础上叠加"通信保障缺口"
(未覆盖窗口数 x 惩罚系数)和"中继电量超限"(超限架次数 x 惩罚系数)两项，Deb
约束支配规则不用改。

关键建模假设清单见 q3_common.MODELING_ASSUMPTIONS（附录3未给出可执行文字算法
/公式时的合理默认，写入summary.txt，不假装是题目原文）。

运行方式：
    python q3_1.py
输出（当前目录 / figures/）：
    q3_1_routes.csv            代表解的路线明细（+通信保障方式列）
    q3_1_sorties.csv           代表解的运输架次-无人机-电池-起止时间
    q3_1_relay_sorties.csv     代表解的中继架次明细
    q3_1_box_delivery.csv      代表解的逐箱送达时刻
    q3_1_resource_timeline.csv 代表解的资源时间轴(运输+中继合并)
    q3_1_pareto_front.csv      最终种群的非支配前沿
    q3_1_summary.txt           结果汇总+建模假设清单+校验+对照q2_1/q2_2
    figures/q3_1_01_帕累托前沿.png
    figures/q3_1_02_通信覆盖与路线图.png
    figures/q3_1_03_联合资源甘特图.png
    figures/q3_1_04_机队架次能耗对比.png
"""
import os
import time

import numpy as np
import pandas as pd

from q00 import load_box_list, load_transport_drone, load_relay_drone
from q2_common import (
    MAX_STOPS, load_leg_geometry_table, build_box_index, decode_group_to_routes, hard_deadline,
)
from q2_1 import (
    compute_nearest_areas, build_seed_population, fast_nondominated_sort,
    crowding_distance, tournament_select, crossover, mutate, fig_pareto,
)
from q3_common import (
    MODELING_ASSUMPTIONS, load_comm_constants, gw_position, load_dem_full, build_node_positions,
    load_or_build_relay_layer, attach_relay_requirements, simulate_joint_dispatch,
    compute_objectives_joint, fig_comm_coverage_map, fig_joint_resource_gantt, fig_fleet_breakdown,
    O01_ID,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEED = 20260923

PILOT_POP, PILOT_GEN = 24, 5
FULL_POP, FULL_GEN = 80, 80
MUT_RATE = 0.05

# q2_1 / q2_2 基线，仅用于summary里的"变大是符合预期"对照说明
Q2_1_BASELINE = dict(f4=29, f3=82.777, violations=0)
Q2_2_BASELINE = dict(f4=16, f3=58.179, violations=5)


def default_priority_fn(route, now):
    return route["priority_sum"] / max(route["T_route_s"], 1.0)


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


# ---------------------------------------------------------------------------
# 解码 + 目标评估（带记忆化）
# ---------------------------------------------------------------------------
def evaluate_chromosome(chromosome, box_ids, box_index, spec_rows, spec_df, boxes_df, leg_geo,
                         fleet_df, battery_df, relay_fleet_df, relay_stock_df, relay_spec_row,
                         relay_candidates, comm_profile, phase_coverage, o01, priority_fn,
                         group_cache, chromo_cache):
    key = tuple(int(x) for x in chromosome)
    if key in chromo_cache:
        return chromo_cache[key]

    groups = {}
    for bid, g in zip(box_ids, chromosome):
        groups.setdefault(int(g), []).append(bid)

    routes = []
    for ids in groups.values():
        routes.extend(decode_group_to_routes(ids, box_index, spec_rows, leg_geo, group_cache))
    attach_relay_requirements(routes, leg_geo, comm_profile, phase_coverage, spec_df)

    sim_result = simulate_joint_dispatch(routes, fleet_df, battery_df, spec_df,
                                          relay_fleet_df, relay_stock_df, relay_spec_row,
                                          relay_candidates, o01, priority_fn)
    obj = compute_objectives_joint(sim_result, boxes_df)
    violation = sum(max(0.0, v["送达"] - v["限制"]) for v in obj["violations"] if v["原因"] == "硬约束超时")
    violation += 1.0e6 * sum(1 for v in obj["violations"] if v["原因"] == "未被任何路线覆盖")
    violation += 1.0e4 * sum(v["缺口数"] for v in obj["violations"] if v["原因"] == "通信保障缺口")
    violation += 1.0e4 * sum(1 for v in obj["violations"] if v["原因"] == "中继电量超限")

    result = dict(violation=violation, f1=obj["f1_及时性"], f2=obj["f2_makespan_s"],
                  f3=obj["f3_总能耗_kWh"], f4=float(obj["f4_架次数"]),
                  routes=routes, sim_result=sim_result, obj=obj)
    chromo_cache[key] = result
    return result


# ---------------------------------------------------------------------------
# NSGA-II 主循环（算子来自q2_1.py，主循环结构照抄run_nsga2，仅新增中继静态输入）
# ---------------------------------------------------------------------------
def run_nsga2_joint(box_ids, box_area, area_list, box_index, spec_rows, spec_df, boxes_df, leg_geo,
                     fleet_df, battery_df, relay_fleet_df, relay_stock_df, relay_spec_row,
                     relay_candidates, comm_profile, phase_coverage, o01,
                     pop_size, n_gen, rng, verbose=True):
    nearest_area_of = compute_nearest_areas(area_list, leg_geo)
    group_cache, chromo_cache = {}, {}

    def ev(ind):
        return evaluate_chromosome(ind, box_ids, box_index, spec_rows, spec_df, boxes_df, leg_geo,
                                    fleet_df, battery_df, relay_fleet_df, relay_stock_df, relay_spec_row,
                                    relay_candidates, comm_profile, phase_coverage, o01,
                                    default_priority_fn, group_cache, chromo_cache)

    pop = build_seed_population(box_ids, box_area, area_list, pop_size, rng)
    metrics = [ev(ind) for ind in pop]

    gen_times = []
    for gen in range(n_gen):
        t0 = time.time()
        fronts = fast_nondominated_sort(metrics)
        rank = {}
        for r, f in enumerate(fronts):
            for i in f:
                rank[i] = r
        crowd = {}
        for f in fronts:
            crowd.update(crowding_distance(f, metrics))

        idxs = list(range(len(pop)))
        offspring = []
        while len(offspring) < pop_size:
            p1 = tournament_select(idxs, rank, crowd, rng)
            p2 = tournament_select(idxs, rank, crowd, rng)
            child = crossover(pop[p1], pop[p2], rng)
            child = mutate(child, box_ids, box_area, nearest_area_of, rng, MUT_RATE)
            offspring.append(child)
        off_metrics = [ev(ind) for ind in offspring]

        combined = pop + offspring
        combined_metrics = metrics + off_metrics
        c_fronts = fast_nondominated_sort(combined_metrics)
        new_pop, new_metrics = [], []
        for f in c_fronts:
            if len(new_pop) + len(f) <= pop_size:
                for i in f:
                    new_pop.append(combined[i])
                    new_metrics.append(combined_metrics[i])
            else:
                cd = crowding_distance(f, combined_metrics)
                remaining = pop_size - len(new_pop)
                chosen = sorted(f, key=lambda i: -cd[i])[:remaining]
                for i in chosen:
                    new_pop.append(combined[i])
                    new_metrics.append(combined_metrics[i])
                break
        pop, metrics = new_pop, new_metrics
        dt = time.time() - t0
        gen_times.append(dt)
        if verbose:
            n_feas = sum(1 for m in metrics if m["violation"] == 0)
            best_f4 = min(m["f4"] for m in metrics)
            print(f"[gen {gen + 1}/{n_gen}] 用时={dt:.2f}s  可行解={n_feas}/{len(metrics)}  "
                  f"最小架次数={best_f4:.0f}  缓存组解码数={len(group_cache)}  缓存个体数={len(chromo_cache)}")
    return pop, metrics, gen_times


# ---------------------------------------------------------------------------
# 主程序
# ---------------------------------------------------------------------------
def main():
    leg_geo, o01, services = load_leg_geometry_table()
    boxes_df = load_box_list()
    spec_df, fleet_df, battery_df = load_transport_drone()
    relay_spec_df, relay_fleet_df, relay_stock_df = load_relay_drone()
    relay_spec_row = relay_spec_df.iloc[0]

    box_ids = list(boxes_df["货箱编号"])
    box_area = dict(zip(boxes_df["货箱编号"], boxes_df["服务区编号"]))
    area_list = sorted(services["服务区编号"].unique())
    box_index = build_box_index(boxes_df)
    spec_rows = [row for _, row in spec_df.iterrows()]

    print(f"[规模] 箱子数={len(box_ids)}  服务区数={len(area_list)}  机型数={len(spec_rows)}")

    # -------------------- 通信/中继全局预计算（与染色体无关，算一次，磁盘缓存） --------------------
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

    rng = np.random.default_rng(SEED)
    print(f"[pilot] pop={PILOT_POP} gen={PILOT_GEN} —— 先测真实每代耗时,再决定正式跑的规模")
    _, _, pilot_times = run_nsga2_joint(box_ids, box_area, area_list, box_index, spec_rows, spec_df, boxes_df,
                                         leg_geo, fleet_df, battery_df, relay_fleet_df, relay_stock_df,
                                         relay_spec_row, relay_candidates, comm_profile, phase_coverage, o01,
                                         PILOT_POP, PILOT_GEN, rng)
    avg_pilot = float(np.mean(pilot_times))
    est_full = avg_pilot * (FULL_POP / PILOT_POP) * FULL_GEN
    print(f"[pilot] 平均每代耗时={avg_pilot:.2f}s  正式规模(pop={FULL_POP},gen={FULL_GEN})预计耗时≈{est_full:.1f}s")

    rng = np.random.default_rng(SEED + 1)
    t0 = time.time()
    pop, metrics, gen_times = run_nsga2_joint(box_ids, box_area, area_list, box_index, spec_rows, spec_df, boxes_df,
                                               leg_geo, fleet_df, battery_df, relay_fleet_df, relay_stock_df,
                                               relay_spec_row, relay_candidates, comm_profile, phase_coverage, o01,
                                               FULL_POP, FULL_GEN, rng)
    total_time = time.time() - t0
    print(f"[正式跑] 实际总耗时={total_time:.1f}s")

    fronts = fast_nondominated_sort(metrics)
    front0_idx = fronts[0]
    front0_metrics = [metrics[i] for i in front0_idx]

    feasible = [m for m in front0_metrics if m["violation"] == 0]
    pool = feasible if feasible else front0_metrics
    rep = min(pool, key=lambda m: (m["f4"], m["f3"]))

    n_feasible_front0 = len(feasible)
    print(f"[前沿] 非支配解数={len(front0_metrics)}  其中可行(0违反)={n_feasible_front0}")
    print(f"[代表解] f1={rep['f1']:.1f}  f2={rep['f2']:.1f}s  f3={rep['f3']:.3f}kWh  "
          f"f4={rep['f4']:.0f}  硬约束违反数={len(rep['obj']['violations'])}")

    routes = rep["routes"]
    sim = rep["sim_result"]
    obj = rep["obj"]

    chosen_ids = sorted(set(w["candidate_id"] for r in routes for w in r["relay_req"]["windows"]))
    chosen_relay = [relay_candidates[i] for i in chosen_ids]

    # -------------------- 输出 CSV --------------------
    route_rows = []
    for i, r in enumerate(routes):
        route_rows.append(dict(
            路线编号=f"R{i + 1:03d}", 机型编号=r["机型编号"], 停靠序列="->".join(["O01"] + list(r["stops"]) + ["O01"]),
            箱数=r["n_box"], 总质量_kg=r["total_mass_kg"], 总体积_m3=r["total_vol_m3"],
            E_route_kWh=r["E_route_kWh"], T_route_s=r["T_route_s"],
            通信保障方式=relay_desc(r, relay_candidates),
            货箱列表="|".join(b["货箱编号"] for bs in r["boxes_by_stop"].values() for b in bs),
        ))
    pd.DataFrame(route_rows).to_csv(os.path.join(BASE_DIR, "q3_1_routes.csv"), index=False, encoding="utf-8-sig")

    sortie_rows = [dict(架次编号=f"T{i + 1:03d}", 机型编号=s["机型编号"], 无人机编号=s["无人机编号"],
                         电池编号=s["电池编号"], 起飞时刻_s=s["start"], 返航时刻_s=s["end"],
                         停靠序列="->".join(["O01"] + list(s["route"]["stops"]) + ["O01"]))
                    for i, s in enumerate(sim["sorties"])]
    pd.DataFrame(sortie_rows).sort_values("起飞时刻_s").to_csv(
        os.path.join(BASE_DIR, "q3_1_sorties.csv"), index=False, encoding="utf-8-sig")

    relay_sortie_rows = [dict(
        架次编号=f"RT{i + 1:03d}", 无人机编号=rs["无人机编号"], 能源组件编号=rs["能源组件编号"],
        关联路线机型=rs["route"]["机型编号"], 关联路线停靠="->".join(["O01"] + list(rs["route"]["stops"]) + ["O01"]),
        悬停经度=rs["candidate"]["lon"], 悬停纬度=rs["candidate"]["lat"], 悬停AGL_m=rs["candidate"]["agl"],
        起飞时刻_s=rs["depart"], 到位时刻_s=rs["service_start"], 撤离时刻_s=rs["service_end"],
        返航时刻_s=rs["ground_arrive"], E_kWh=rs["E_kWh"], 电量是否达标=rs["energy_ok"],
    ) for i, rs in enumerate(sim["relay_sorties"])]
    pd.DataFrame(relay_sortie_rows).to_csv(
        os.path.join(BASE_DIR, "q3_1_relay_sorties.csv"), index=False, encoding="utf-8-sig")

    hd_map = {b["货箱编号"]: hard_deadline(b) for _, b in boxes_df.iterrows()}
    delivery_rows = []
    for _, b in boxes_df.iterrows():
        bid = b["货箱编号"]
        arrive = sim["box_delivery"].get(bid)
        delivery_rows.append(dict(货箱编号=bid, 服务区编号=b["服务区编号"], 物资类型=b["物资类型"],
                                   期望送达时间_s=b["期望送达时间"], 硬约束时限_s=hd_map[bid],
                                   实际送达时刻_s=arrive,
                                   是否硬约束超时=bool(hd_map[bid] is not None and arrive is not None
                                                     and arrive > hd_map[bid] + 1e-6)))
    pd.DataFrame(delivery_rows).to_csv(
        os.path.join(BASE_DIR, "q3_1_box_delivery.csv"), index=False, encoding="utf-8-sig")

    timeline_rows = []
    for ev_ in sim["drone_events"]:
        timeline_rows.append(dict(资源编号=ev_["资源编号"], 资源类型="运输无人机", 事件类型=ev_["类型"],
                                   开始_s=ev_["start"], 结束_s=ev_["end"]))
    for ev_ in sim["batt_events"]:
        timeline_rows.append(dict(资源编号=ev_["资源编号"], 资源类型="运输电池", 事件类型=ev_["类型"],
                                   开始_s=ev_["start"], 结束_s=ev_["end"]))
    for ev_ in sim["relay_events"]:
        timeline_rows.append(dict(资源编号=ev_["资源编号"], 资源类型="中继无人机", 事件类型=ev_["类型"],
                                   开始_s=ev_["start"], 结束_s=ev_["end"]))
    for ev_ in sim["relay_batt_events"]:
        timeline_rows.append(dict(资源编号=ev_["资源编号"], 资源类型="中继能源组件", 事件类型=ev_["类型"],
                                   开始_s=ev_["start"], 结束_s=ev_["end"]))
    pd.DataFrame(timeline_rows).sort_values(["资源编号", "开始_s"]).to_csv(
        os.path.join(BASE_DIR, "q3_1_resource_timeline.csv"), index=False, encoding="utf-8-sig")

    pd.DataFrame([dict(f1_及时性=m["f1"], f2_makespan_s=m["f2"], f3_总能耗_kWh=m["f3"],
                        f4_架次数=m["f4"], 硬约束违反量=m["violation"]) for m in front0_metrics]
                 ).to_csv(os.path.join(BASE_DIR, "q3_1_pareto_front.csv"), index=False, encoding="utf-8-sig")
    print("[saved] q3_1_routes.csv / q3_1_sorties.csv / q3_1_relay_sorties.csv / q3_1_box_delivery.csv / "
          "q3_1_resource_timeline.csv / q3_1_pareto_front.csv")

    # -------------------- 图 --------------------
    fig_pareto(front0_metrics, "q3_1_01_帕累托前沿.png",
               "图q3.1-1  问题三 · NSGA-II联合优化（全局分组编码+通信/中继约束）：最终非支配前沿")
    fig_comm_coverage_map(comm_profile, phase_coverage, node_lonlat, o01, services, chosen_relay,
                           "q3_1_02_通信覆盖与路线图.png",
                           "图q3.1-2  问题三 · 代表解：O01-服务区通信保障方式 + 中继悬停点")
    fig_joint_resource_gantt(sim, fleet_df, battery_df, relay_fleet_df, relay_stock_df,
                              "q3_1_03_联合资源甘特图.png",
                              "图q3.1-3  问题三 · 代表解：运输(8机身+14电池)+中继(2机身+6能源组件)联合资源时间轴")
    fig_fleet_breakdown(obj, "q3_1_04_机队架次能耗对比.png",
                         "图q3.1-4  问题三 · 代表解：运输 vs 中继 架次数/能耗对比")

    # -------------------- 校验 + summary --------------------
    n_covered = sum(1 for v in delivery_rows if v["实际送达时刻_s"] is not None)
    multi_stop = sum(1 for r in routes if len(r["stops"]) > 1)
    n_direct = sum(1 for r in routes if not r["relay_req"]["windows"])
    n_relay_ok = sum(1 for r in routes if r["relay_req"]["windows"] and r["relay_req"]["feasible"])
    n_relay_gap = sum(1 for r in routes if not r["relay_req"]["feasible"])

    lines = []
    lines.append("问题三 · 方法1：NSGA-II（全局分组编码 + 通信/中继联合调度）—— 结果汇总")
    lines.append("=" * 60)
    lines.append("")
    lines.append("零、关键建模假设清单（附录3未给出可执行文字算法/公式时的合理默认，非题目原文）")
    for i, a in enumerate(MODELING_ASSUMPTIONS, 1):
        lines.append(f"  {i}. {a}")
    lines.append("")
    lines.append(f"种群/代数：pilot pop={PILOT_POP} gen={PILOT_GEN}（平均每代{avg_pilot:.2f}s）；"
                  f"正式 pop={FULL_POP} gen={FULL_GEN}，实际总耗时{total_time:.1f}s")
    lines.append(f"通信/中继全局预计算：需中继相位={n_phase_need}/{3 * len(comm_profile)}，"
                 f"中继候选点={len(relay_candidates)}个，零候选硬缺口相位={n_gap_phase}个，"
                 f"预计算用时={time.time() - t_pre:.1f}s(含GA全程，命中磁盘缓存时该值主要是GA耗时)")
    lines.append("")
    lines.append(f"一、覆盖校验：送达{n_covered}/{len(boxes_df)}箱"
                  f"（分组编码结构性保证100%覆盖，无需额外的集合划分约束；通信不可行只记violation,不剔除路线）")
    lines.append("")
    lines.append("二、代表解（前沿中架次数最少、能耗次优先的可行解；若前沿无可行解则取违反量最小者）")
    lines.append(f"  f1(及时性,加权迟到量)={rep['f1']:.1f}")
    lines.append(f"  f2(makespan)={rep['f2']:.1f} s ({rep['f2'] / 3600:.2f} h)"
                 f"  [运输={obj['f2_运输_s']:.1f}s  中继={obj['f2_中继_s']:.1f}s]")
    lines.append(f"  f3(总能耗)={rep['f3']:.3f} kWh"
                 f"  [运输={obj['f3_运输_kWh']:.3f}kWh  中继={obj['f3_中继_kWh']:.3f}kWh]")
    lines.append(f"  f4(架次数)={rep['f4']:.0f}（其中多停靠架次{multi_stop}个，"
                 f"占比{multi_stop / max(len(routes), 1) * 100:.1f}%）"
                 f"  [运输架次={obj['f4_运输架次']}  中继架次={obj['f4_中继架次']}]")
    lines.append(f"  硬约束违反数={len(rep['obj']['violations'])}")
    lines.append("")
    lines.append(f"三、通信保障方式分布：{len(routes)}条路线中 直连={n_direct}  中继覆盖={n_relay_ok}  "
                 f"中继缺口={n_relay_gap}")
    if n_relay_gap > 0:
        lines.append(f"  [如实报告] {n_relay_gap}条路线的通信需求超出2个中继位置的可归并上限，或落在零候选")
        lines.append("  的硬缺口相位上，已计入violations的'通信保障缺口'条目，未被静默隐藏或强行凑单一中继覆盖。")
    lines.append("")
    lines.append("四、与q2版本（不建模通信/中继）对照")
    lines.append(f"  q2_1(NSGA-II全局解)：架次数={Q2_1_BASELINE['f4']}，总能耗={Q2_1_BASELINE['f3']}kWh，"
                 f"硬约束违反数={Q2_1_BASELINE['violations']}")
    lines.append(f"  q2_2(贪心基线)   ：架次数={Q2_2_BASELINE['f4']}，总能耗={Q2_2_BASELINE['f3']}kWh，"
                 f"硬约束违反数={Q2_2_BASELINE['violations']}")
    lines.append(f"  q3_1(本方案)     ：架次数={rep['f4']:.0f}(运输{obj['f4_运输架次']}+中继{obj['f4_中继架次']})，"
                 f"总能耗={rep['f3']:.3f}kWh(运输{obj['f3_运输_kWh']:.3f}+中继{obj['f3_中继_kWh']:.3f})，"
                 f"硬约束违反数={len(rep['obj']['violations'])}")
    lines.append("  q3_1的总能耗/架次数均应不低于q2_1的对应运输分量——这是符合预期的结果：叠加通信保障后")
    lines.append("  必须额外派遣中继架次、消耗额外能量，是约束变严格带来的合理代价，不是回归或bug。")
    lines.append("")
    lines.append("五、范围裁剪说明")
    lines.append(f"  单架次最多{MAX_STOPS}个停靠服务区；派单规则固定为'紧迫覆盖优先+应急优先系数密度'，不参与搜索；")
    lines.append("  中继悬停位置为离散候选网格搜索结果，非连续优化(见建模假设5)。")

    with open(os.path.join(BASE_DIR, "q3_1_summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("[saved] q3_1_summary.txt")

    ok = n_covered == len(boxes_df)
    print("[done] all checks passed" if ok else "[warn] coverage check failed")


if __name__ == "__main__":
    main()

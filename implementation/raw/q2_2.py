# -*- coding: utf-8 -*-
"""
2026年研究生数学建模竞赛 D题 —— 问题二 · 方法2：仿真派单 + 外层优先级预设扫描（q2_2）

定位：不追求全局最优（那是q2_1.py的NSGA-II的任务），而是"简单可解释的构造式
基线 + 派单规则的外层扫描"——

    1. 复用问题一的单站集合划分（q1_2_common.enumerate_candidates +
       solve_set_partitioning，权重取"均衡"），得到N0=18条单站基线路线；
    2. 把每条单站批次转成q2_common的路线dict（q2_common.best_type_for_group），
       再用贪心算法尝试把不同服务区的路线两两/三合一合并成多站路线（O01->Si->
       Sj->...->O01），接受条件与排序信号统一用"能耗节省"（合并对架次数的贡献
       固定是-1/-2，没有区分度，能耗节省才是唯一会变化的信号）；
    3. 路线合并结果固定住之后，只扫描simulate_dispatch的priority_fn——3组
       互斥的派单哲学（均衡=应急优先系数密度/紧迫优先=纯软时限余量/能耗优先=
       单箱能耗），对比非紧迫箱子的软目标(f1及时性/f2 makespan)如何随派单规则
       变化（simulate_dispatch内置的"紧迫覆盖优先于priority_fn"逻辑会让f4架次数
       与硬约束违反数在3组预设间结构性打平，这是预期结果不是bug）。

运行方式：
    python q2_2.py
输出（当前目录 / figures/）：
    q2_2_routes.csv           合并后的路线明细
    q2_2_sorties.csv          主预设的架次-无人机-电池-起止时间
    q2_2_box_delivery.csv     主预设的逐箱送达时刻
    q2_2_resource_timeline.csv 主预设的资源时间轴（飞行/充电区间）
    q2_2_preset_compare.csv   3组预设的 f1-f4 + 违反数对比表
    q2_2_summary.txt          结果汇总+校验+预设对比说明
    figures/q2_2_01_路线结构图.png
    figures/q2_2_02_资源甘特图.png
    figures/q2_2_03_优先级权衡对比.png
"""
import math
import os

import numpy as np
import pandas as pd

from q00 import (
    load_transport_drone, style_ax, savefig,
    SURFACE, INK, INK2, MUTED, GRID, BASELINE, CAT, DRONE_ORDER, DRONE_COLOR,
)
from q1_2_common import (
    load_base_data, enumerate_candidates, solve_set_partitioning, total_metrics, validate_selection,
)
from q2_common import (
    MAX_STOPS, URGENCY_MARGIN_S, load_leg_geometry_table, build_box_index,
    best_type_for_group, hard_deadline, simulate_dispatch, compute_objectives,
    fig_route_map, fig_resource_gantt,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BASELINE_COST_WEIGHTS = (1 / 3, 1 / 3, 1 / 3)  # 呼应q1_21.py"均衡"权重的本地副本，不import q1_21.py
MERGE_EPS_KWH = 1e-6


# ---------------------------------------------------------------------------
# 1. 基线构造：问题一单站集合划分（只做一次）
# ---------------------------------------------------------------------------
def baseline_cost(candidates, boxes_df, weights=BASELINE_COST_WEIGHTS):
    """q1_21.py三组权重(均衡/架次优先/能耗优先)都收敛到同一个N0=18方案(payoff表
    退化)，所以选哪组都一样；选均衡只是让本脚本的起点数字与q2_1_summary.txt里
    已引用的"问题一N=18基线"保持一致，不引入第4个不同的基线数字。"""
    w_n, w_e, w_t = weights
    n_min = boxes_df["服务区编号"].nunique()
    n_max = len(boxes_df)
    n_range = max(n_max - n_min, 1)
    e = candidates["E_batch_kWh"].values
    t = candidates["T_batch_s"].values
    n_contrib = np.full(len(candidates), 1.0 / n_range)
    return w_n * n_contrib + w_e * (e / e.max()) + w_t * (t / t.max())


# ---------------------------------------------------------------------------
# 2. 单站批次 / 合并组 -> q2_common 路线dict（统一走best_type_for_group,不手搭字段）
# ---------------------------------------------------------------------------
def route_from_areas(areas, boxes_by_area, spec_df, leg_geo):
    trimmed = {a: boxes_by_area[a] for a in areas}
    res = best_type_for_group(areas, trimmed, spec_df, leg_geo)
    if res is None:
        return None
    res["boxes_by_stop"] = trimmed
    res["priority_sum"] = sum(b["应急优先系数"] for bs in trimmed.values() for b in bs)
    return res


# ---------------------------------------------------------------------------
# 3. 贪心多站合并（能耗节省驱动：架次数每次合并的收益固定是-1/-2,没有区分度）
# ---------------------------------------------------------------------------
def arrival_absolute_safe(route):
    """必要条件预筛：假设立刻起飞(now=0)都赶不上硬时限的合并,无论后续调度怎么
    排都救不回来,直接拒绝(不是充分条件,真正的可行性由simulate_dispatch决定)。"""
    for area in route["stops"]:
        t_arr = route["arrival_rel_s"][area]
        for b in route["boxes_by_stop"][area]:
            hd = hard_deadline(b)
            if hd is not None and t_arr > hd + 1e-6:
                return False
    return True


def try_merge(routes_group, spec_df, leg_geo):
    areas = [a for r in routes_group for a in r["stops"]]
    boxes_by_area = {}
    for r in routes_group:
        boxes_by_area.update(r["boxes_by_stop"])
    merged = route_from_areas(areas, boxes_by_area, spec_df, leg_geo)
    if merged is None or not arrival_absolute_safe(merged):
        return None
    return merged


def greedy_merge_routes(routes, spec_df, leg_geo, log=None):
    """两两合并优先；只有当两两合并已经找不到收益时才试三合一(否则AB两两不
    达标但ABC三合一达标的情况会被漏掉)。复杂度：n<=18时每轮两两扫描<=C(18,2)=153
    对,每对<=3次evaluate_route(3种机型),最多n-1轮成功合并,全程纯算术无DEM/IO,
    运行时间可忽略。"""
    active = list(routes)
    while True:
        best = None  # (saving, idx_tuple, merged_route)
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                ra, rb = active[i], active[j]
                if set(ra["stops"]) & set(rb["stops"]):
                    continue  # 同服务区的兄弟批次不合并
                if len(ra["stops"]) + len(rb["stops"]) > MAX_STOPS:
                    continue
                merged = try_merge([ra, rb], spec_df, leg_geo)
                if merged is None:
                    continue
                saving = ra["E_route_kWh"] + rb["E_route_kWh"] - merged["E_route_kWh"]
                if saving > MERGE_EPS_KWH and (best is None or saving > best[0]):
                    best = (saving, (i, j), merged)
        if best is None:
            for i in range(len(active)):
                for j in range(i + 1, len(active)):
                    for k in range(j + 1, len(active)):
                        ra, rb, rc = active[i], active[j], active[k]
                        union = set(ra["stops"]) | set(rb["stops"]) | set(rc["stops"])
                        if len(union) != len(ra["stops"]) + len(rb["stops"]) + len(rc["stops"]) or len(union) > MAX_STOPS:
                            continue
                        merged = try_merge([ra, rb, rc], spec_df, leg_geo)
                        if merged is None:
                            continue
                        saving = ra["E_route_kWh"] + rb["E_route_kWh"] + rc["E_route_kWh"] - merged["E_route_kWh"]
                        if saving > MERGE_EPS_KWH and (best is None or saving > best[0]):
                            best = (saving, (i, j, k), merged)
        if best is None:
            break
        saving, idxs, merged = best
        removed = [active[t] for t in idxs]
        active = [r for t, r in enumerate(active) if t not in idxs]
        active.append(merged)
        if log is not None:
            log.append(dict(areas=merged["stops"], 机型编号=merged["机型编号"], n_inputs=len(idxs),
                             E_before=sum(r["E_route_kWh"] for r in removed), E_after=merged["E_route_kWh"],
                             saving=saving))
    return active


# ---------------------------------------------------------------------------
# 4. 三组派单优先级预设（互斥哲学,最大化扫描信息量;本地定义,不import q2_1.py）
# ---------------------------------------------------------------------------
def priority_balanced(route, now):
    return route["priority_sum"] / max(route["T_route_s"], 1.0)


def _soft_min_slack(route, now):
    """纯软时限余量：对**所有**箱子(不只是硬约束箱)按期望送达时间算slack,
    是simulate_dispatch内置'紧迫覆盖优先'逻辑(只看硬约束)覆盖不到的维度。"""
    slacks = [b["期望送达时间"] - (now + route["arrival_rel_s"][area])
              for area, boxes in route["boxes_by_stop"].items() for b in boxes]
    return min(slacks) if slacks else math.inf


def priority_urgency(route, now):
    return -_soft_min_slack(route, now) / URGENCY_MARGIN_S


def priority_energy(route, now):
    return -route["E_route_kWh"] / max(route["n_box"], 1)  # 单箱能耗,不用总能耗——否则系统性打压多站路线


PRESETS = [("均衡", priority_balanced), ("紧迫优先", priority_urgency), ("能耗优先", priority_energy)]


# ---------------------------------------------------------------------------
# 5. 可视化：预设权衡对比
# ---------------------------------------------------------------------------
def fig_preset_compare(preset_results, main_name, filename, title):
    import matplotlib.pyplot as plt
    names = [n for n, _ in PRESETS]
    colors = {n: CAT[i] for i, n in enumerate(names)}
    metrics = [
        ("f1_及时性", "f1 及时性（加权迟到量,越低越好）", 1.0, "{:.0f}"),
        ("f2_makespan_s", "f2 makespan (h,越低越好)", 1.0 / 3600.0, "{:.2f}"),
        ("f3_总能耗_kWh", "f3 总能耗 (kWh)", 1.0, "{:.2f}"),
        ("f4_架次数", "f4 架次数（结构性打平）", 1.0, "{:.0f}"),
    ]
    fig, axes = plt.subplots(1, 4, figsize=(15.5, 4.8))
    x = np.arange(len(names))
    for ax, (key, label, scale, fmt) in zip(axes, metrics):
        vals = [preset_results[n]["obj"][key] * scale for n in names]
        bars = ax.bar(x, vals, color=[colors[n] for n in names], width=0.6, zorder=3)
        for i, n in enumerate(names):
            if n == main_name:
                bars[i].set_edgecolor(INK)
                bars[i].set_linewidth(2.2)
        vmax = max(vals) if vals else 1.0
        for i, v in enumerate(vals):
            ax.annotate(fmt.format(v), (i, v), xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=8.4, color=INK)
        ax.set_xticks(x)
        ax.set_xticklabels(names, fontsize=8.8)
        ax.set_ylim(0, vmax * 1.18 if vmax > 0 else 1.0)
        style_ax(ax, grid_axis="y")
        ax.set_title(label, fontsize=9.6, color=INK, loc="left")

    n_viol = {n: len(preset_results[n]["obj"]["violations"]) for n in names}
    caption = ("硬约束违反数：" + "  ".join(f"{n}={n_viol[n]}" for n in names)
               + f"　（黑框=主方案：{main_name}）")
    fig.text(0.02, 0.90, caption, fontsize=9.4, color=INK2)
    fig.suptitle(title, fontsize=12.6, fontweight="bold", color=INK, x=0.02, y=0.99, ha="left", va="top")
    fig.subplots_adjust(left=0.045, right=0.98, top=0.78, bottom=0.15, wspace=0.32)
    savefig(fig, filename)


# ---------------------------------------------------------------------------
# 主程序
# ---------------------------------------------------------------------------
def main():
    leg_geo, o01, services = load_leg_geometry_table()
    boxes_df, spec_df, qmax_lookup, geo_table = load_base_data()
    _, fleet_df, battery_df = load_transport_drone()
    box_index = build_box_index(boxes_df)

    print(f"[规模] 箱子数={len(boxes_df)}  服务区数={boxes_df['服务区编号'].nunique()}  机型数={len(spec_df)}")

    # -------------------- 1. 基线构造（问题一单站集合划分） --------------------
    candidates = enumerate_candidates(boxes_df, spec_df, geo_table, qmax_lookup)
    cost = baseline_cost(candidates, boxes_df)
    selected = candidates.iloc[solve_set_partitioning(candidates, boxes_df, cost)].reset_index(drop=True)
    N0, E0, T0 = total_metrics(selected)
    ok0, msg0 = validate_selection(selected, boxes_df)
    print(f"[基线] {msg0}")
    print(f"[基线] N0={N0}  E0={E0:.3f} kWh  T0={T0:.1f} s")
    if not ok0:
        raise RuntimeError("问题一单站基线覆盖校验失败,不应该发生: " + msg0)

    # -------------------- 2. 单站批次 -> q2_common 路线dict --------------------
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

    # -------------------- 3. 贪心多站合并 --------------------
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

    # -------------------- 4. 三组派单优先级预设扫描 --------------------
    preset_results = {}
    for name, fn in PRESETS:
        sim = simulate_dispatch(merged_routes, fleet_df, battery_df, spec_df, fn)
        obj = compute_objectives(sim, boxes_df)
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

    def _all_close(vals, tol=1e-6):
        vals = list(vals)
        return all(abs(v - vals[0]) <= tol * max(1.0, abs(vals[0])) for v in vals)

    f4_set = set(int(preset_results[n]["obj"]["f4_架次数"]) for n, _ in PRESETS)
    f4_flat = len(f4_set) == 1 and f4_set == {len(merged_routes)}
    cov_flat = all(len(preset_results[n]["sim"]["box_delivery"]) == len(boxes_df) for n, _ in PRESETS)
    urgency_worse = violations("紧迫优先") > violations("均衡")

    f1_vals = [preset_results[n]["obj"]["f1_及时性"] for n, _ in PRESETS]
    f2_vals = [preset_results[n]["obj"]["f2_makespan_s"] for n, _ in PRESETS]
    f3_vals = [preset_results[n]["obj"]["f3_总能耗_kWh"] for n, _ in PRESETS]
    soft_flat = _all_close(f1_vals) and _all_close(f2_vals) and _all_close(f3_vals)
    routes_with_hard_box = sum(
        1 for r in merged_routes
        if any(hard_deadline(b) is not None for bs in r["boxes_by_stop"].values() for b in bs))
    if soft_flat:
        print(f"[预设对比] f1/f2/f3在3组预设间也完全打平(不只是结构性恒等的f4/覆盖)——"
              f"{routes_with_hard_box}/{len(merged_routes)}条合并路线自带硬时限箱,"
              f"内置紧迫覆盖优先规则几乎在每个派单节点都生效,priority_fn实际未被采用")

    # -------------------- 输出 CSV --------------------
    route_rows = []
    for i, r in enumerate(merged_routes):
        route_rows.append(dict(
            路线编号=f"R{i + 1:03d}", 机型编号=r["机型编号"], 停靠序列="->".join(["O01"] + list(r["stops"]) + ["O01"]),
            箱数=r["n_box"], 总质量_kg=r["total_mass_kg"], 总体积_m3=r["total_vol_m3"],
            E_route_kWh=r["E_route_kWh"], T_route_s=r["T_route_s"],
            货箱列表="|".join(b["货箱编号"] for bs in r["boxes_by_stop"].values() for b in bs),
        ))
    pd.DataFrame(route_rows).to_csv(os.path.join(BASE_DIR, "q2_2_routes.csv"), index=False, encoding="utf-8-sig")

    sortie_rows = [dict(架次编号=f"T{i + 1:03d}", 机型编号=s["机型编号"], 无人机编号=s["无人机编号"],
                         电池编号=s["电池编号"], 起飞时刻_s=s["start"], 返航时刻_s=s["end"],
                         停靠序列="->".join(["O01"] + list(s["route"]["stops"]) + ["O01"]))
                    for i, s in enumerate(main_sim["sorties"])]
    pd.DataFrame(sortie_rows).sort_values("起飞时刻_s").to_csv(
        os.path.join(BASE_DIR, "q2_2_sorties.csv"), index=False, encoding="utf-8-sig")

    hd_map = {b["货箱编号"]: hard_deadline(b) for _, b in boxes_df.iterrows()}
    delivery_rows = []
    for _, b in boxes_df.iterrows():
        bid = b["货箱编号"]
        arrive = main_sim["box_delivery"].get(bid)
        delivery_rows.append(dict(货箱编号=bid, 服务区编号=b["服务区编号"], 物资类型=b["物资类型"],
                                   期望送达时间_s=b["期望送达时间"], 硬约束时限_s=hd_map[bid],
                                   实际送达时刻_s=arrive,
                                   是否硬约束超时=bool(hd_map[bid] is not None and arrive is not None and arrive > hd_map[bid] + 1e-6)))
    pd.DataFrame(delivery_rows).to_csv(os.path.join(BASE_DIR, "q2_2_box_delivery.csv"), index=False, encoding="utf-8-sig")

    timeline_rows = []
    for ev in main_sim["drone_events"]:
        timeline_rows.append(dict(资源编号=ev["资源编号"], 资源类型="无人机", 事件类型=ev["类型"], 开始_s=ev["start"], 结束_s=ev["end"]))
    for ev in main_sim["batt_events"]:
        timeline_rows.append(dict(资源编号=ev["资源编号"], 资源类型="电池", 事件类型=ev["类型"], 开始_s=ev["start"], 结束_s=ev["end"]))
    pd.DataFrame(timeline_rows).sort_values(["资源编号", "开始_s"]).to_csv(
        os.path.join(BASE_DIR, "q2_2_resource_timeline.csv"), index=False, encoding="utf-8-sig")

    compare_rows = [dict(预设名称=n, f1_及时性=preset_results[n]["obj"]["f1_及时性"],
                          f2_makespan_s=preset_results[n]["obj"]["f2_makespan_s"],
                          f3_总能耗_kWh=preset_results[n]["obj"]["f3_总能耗_kWh"],
                          f4_架次数=preset_results[n]["obj"]["f4_架次数"],
                          硬约束违反数=len(preset_results[n]["obj"]["violations"]),
                          是否主方案=(n == main_name)) for n, _ in PRESETS]
    pd.DataFrame(compare_rows).to_csv(os.path.join(BASE_DIR, "q2_2_preset_compare.csv"), index=False, encoding="utf-8-sig")
    print("[saved] q2_2_routes.csv / q2_2_sorties.csv / q2_2_box_delivery.csv / "
          "q2_2_resource_timeline.csv / q2_2_preset_compare.csv")

    # -------------------- 图 --------------------
    fig_route_map(merged_routes, o01, services, "q2_2_01_路线结构图.png",
                  f"图q2.2-1  问题二 · 贪心构造+合并：路线结构图（N={len(merged_routes)}架次）")
    fig_resource_gantt(main_sim, fleet_df, battery_df, "q2_2_02_资源甘特图.png",
                        f"图q2.2-2  问题二 · 贪心构造+合并（{main_name}预设）：8机身+14电池资源时间轴")
    fig_preset_compare(preset_results, main_name, "q2_2_03_优先级权衡对比.png",
                        "图q2.2-3  问题二 · 三组派单优先级预设的四目标权衡对比")

    # -------------------- summary --------------------
    multi_stop = sum(1 for r in merged_routes if len(r["stops"]) > 1)
    lines = []
    lines.append("问题二 · 方法2：仿真派单 + 外层优先级预设扫描 —— 结果汇总")
    lines.append("=" * 60)
    lines.append("")
    lines.append("一、基线构造（问题一单站集合划分,均衡权重）")
    lines.append(f"  {msg0}")
    lines.append(f"  N0={N0}  E0={E0:.3f} kWh  T0={T0:.1f} s")
    lines.append("")
    lines.append("二、贪心多站合并")
    lines.append(f"  合并轮数={len(merge_log)}（两两合并{n_pair}次,三合一{n_triple}次）")
    lines.append(f"  架次数：{len(base_routes)} -> {len(merged_routes)}（其中多停靠架次{multi_stop}个，"
                 f"占比{multi_stop/max(len(merged_routes),1)*100:.1f}%）")
    lines.append(f"  总能耗：{e_base_sum:.3f} -> {e_merged_sum:.3f} kWh（节省{saving_pct:.1f}%）")
    lines.append(f"  合并后箱子覆盖：{len(all_box_ids)}/{len(boxes_df)}箱，去重后{len(set(all_box_ids))}箱 -> "
                 f"{'通过' if ok_cov else '失败'}")
    lines.append("")
    lines.append("三、三组派单优先级预设对比")
    for n, _ in PRESETS:
        obj = preset_results[n]["obj"]
        mark = "  <- 主方案" if n == main_name else ""
        lines.append(f"  [{n}] f1={obj['f1_及时性']:.1f}  f2={obj['f2_makespan_s']:.1f}s"
                     f"({obj['f2_makespan_s']/3600:.2f}h)  f3={obj['f3_总能耗_kWh']:.3f}kWh  "
                     f"f4={obj['f4_架次数']}  违反数={len(obj['violations'])}{mark}")
    lines.append(f"  主方案选择理由：违反数最少（并列时优先均衡）")
    lines.append(f"  结构性打平说明：simulate_dispatch内置'紧迫覆盖优先于priority_fn'的派单规则会强制硬时限")
    lines.append(f"  紧的路线永远排最前，因此三组预设的f4架次数{'确实全部等于'+str(len(merged_routes)) if f4_flat else '未打平(异常,需排查)'}，")
    lines.append(f"  逐箱覆盖也{'全部为80/80' if cov_flat else '未打平(异常,需排查)'}(此两项按设计恒等，不因预设而变)。")
    if soft_flat:
        lines.append(f"  额外发现：本次贪心构造出的{len(merged_routes)}条合并路线里有{routes_with_hard_box}条")
        lines.append(f"  自带硬时限箱(首批保障/医疗物资)，覆盖面很广，导致'紧迫覆盖优先'规则几乎在")
        lines.append(f"  每一个派单节点都被触发——priority_fn实际上从未真正参与过决策，所以连f1/f2/f3")
        lines.append(f"  这三个软目标也在3组预设间完全打平（不是仅f4/覆盖打平）。这是本次贪心基线")
        lines.append(f"  '路线数少、每条路线普遍带硬约束箱'这一构造特点的真实结果，不是bug；也说明")
        lines.append(f"  在这种路线粒度下，外层派单优先级的扫描对本基线没有实际调控空间——若想让三组")
        lines.append(f"  预设产生真实差异，需要更细粒度、非紧迫路线占比更高的路线集合(对照q2_1.py")
        lines.append(f"  的29架次全局解，其中75.9%架次不含多停靠、拆分更细，派单选择空间更大)。")
    else:
        lines.append(f"  三者真正的差异体现在f1/f2这两个软目标上，这是预期结果，不是bug——")
        lines.append(f"  本图(见q2_2_03)要凸显的正是这个差异。")
    if urgency_worse:
        lines.append(f"  [异常提示] '紧迫优先'违反数({violations('紧迫优先')})反而比'均衡'({violations('均衡')})多，"
                     f"不属于预期结果，建议复查_soft_min_slack与硬约束覆盖是否冲突。")
    lines.append("")
    lines.append("四、与q2_1.py（NSGA-II全局分组编码）对照")
    lines.append(f"  q2_2贪心基线：架次数={len(merged_routes)}，主方案硬约束违反数={violations(main_name)}")
    lines.append(f"  q2_1全局解（见q2_1_summary.txt）：架次数=29，硬约束违反数=0")
    lines.append(f"  q2_2架次数更少，是因为贪心合并把更多箱子压进同一条路线（16条里{routes_with_hard_box}条")
    lines.append(f"  带硬时限箱），但也正因为路线更少更'重'，一旦C/B型机身排队，多个硬时限箱会一起被拖")
    lines.append(f"  延，才出现{violations(main_name)}个违反；q2_1的NSGA-II搜索了80代种群，主动避开了这类")
    lines.append(f"  拥堵的分组方式，代价是架次数更高。两者是'更少架次但更容易违约'与'架次更多但0违约'")
    lines.append(f"  的两种不同取舍，量级上可比，不做跨脚本优劣裁决。")
    lines.append("")
    lines.append("五、输出文件清单")
    lines.append("  q2_2_routes.csv / q2_2_sorties.csv / q2_2_box_delivery.csv / q2_2_resource_timeline.csv /")
    lines.append("  q2_2_preset_compare.csv / q2_2_summary.txt / figures/q2_2_01~03.png")
    lines.append("")
    lines.append("六、范围裁剪说明")
    lines.append(f"  单架次最多{MAX_STOPS}个停靠服务区；不建模通信/中继(问题三范畴)；")
    lines.append("  贪心合并是能耗贪心，不是全局最优——本脚本定位为q2_1.py全局NSGA-II之外的可解释")
    lines.append("  构造式基线，两者架次数量级可以对照讨论，但不做跨脚本优劣比较。")

    with open(os.path.join(BASE_DIR, "q2_2_summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("[saved] q2_2_summary.txt")

    ok = ok0 and ok_cov and cov_flat
    print("[done] all checks passed" if ok else "[warn] some checks failed")


if __name__ == "__main__":
    main()

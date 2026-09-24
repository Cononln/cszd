# -*- coding: utf-8 -*-
"""问题三方法1：候选中继点枚举 + 连续通信覆盖筛选。

先固定问题二代表运输方案，再对DEM覆盖范围内的候选悬停点/高度逐架次做
链路预算和地形遮挡检查；在通信不中断的候选中按中继能耗、联合完工时间、
中继架次的分层目标选择方案。
"""
import os, sys, json
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from q00 import load_nodes, load_relay_drone, load_comm_params
from p3_common import (read_base_solution, load_dem_array, _comm_budget, make_node_map,
                       candidate_relays, coverage_for_route, evaluate_plan,
                       save_basic_figures, hard_deadline)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
FIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figures")
os.makedirs(OUT, exist_ok=True); os.makedirs(FIG, exist_ok=True)


def main():
    routes, sorties, boxes = read_base_solution("q2_1")
    o01, services = load_nodes(); arr, transform, bounds = load_dem_array()
    relay_spec_df, relay_fleet, relay_stock = load_relay_drone()
    relay_spec = relay_spec_df.iloc[0]
    budget = _comm_budget(load_comm_params()); node_map = make_node_map(o01, services)
    candidates = candidate_relays(routes, o01, services)

    assignments = {}; rows = []; route_cov = {}
    for r in routes:
        all_cov = []
        for p in candidates:
            cov = coverage_for_route(r, p, node_map, budget, arr, transform)
            service_s = r["T_route_s"] + float(relay_spec["建链时间"])
            # 只对确实需要中继的方案计中继能耗；直连架次不占用中继资源。
            e = 0.0
            if cov["relay_need"]:
                from p3_common import relay_energy
                e, _ = relay_energy(relay_spec, p, o01, service_s)
            all_cov.append((cov, p, e))
        # 分层选择：先最小通信中断，再最少中继使用，最后中继能耗和高度。
        all_cov.sort(key=lambda x: (x[0]["interrupted_s"], int(x[0]["relay_need"]), x[2], x[1]["height_m"]))
        cov, p, e = all_cov[0]
        assignments[r["route_id"]] = {**cov, "relay": p, "relay_energy": e}
        route_cov[r["route_id"]] = all_cov[:10]
        for j, (cc, pp, ee) in enumerate(all_cov[:20]):
            rows.append({"架次编号": r["sortie_id"], "路线编号": r["route_id"], "候选排名": j+1,
                         "中继点": pp["name"], "经度": pp["lon"], "纬度": pp["lat"], "悬停高度_m": pp["height_m"],
                         "通信中断_s": cc["interrupted_s"], "覆盖率": cc["coverage_ratio"], "是否需要中继": cc["relay_need"], "中继能耗_kWh": ee})
    plan = evaluate_plan(routes, assignments, relay_spec, relay_fleet, relay_stock, o01, boxes)

    # 输出路线和中继选择（起飞/返航时刻采用联合排程后的运输时刻）
    relay_map = {x["route_id"]: x for x in plan["relay_schedule"]}
    pd.DataFrame([{"路线编号":r["route_id"], "架次编号":r["sortie_id"], "机型编号":r["机型编号"],
                   "停靠序列":"O01->"+"->".join(r["stops"])+"->O01", "起飞_s":relay_map[r["route_id"]].get("transport_start", r["start"]), "返航_s":relay_map[r["route_id"]].get("transport_end", r["end"]),
                   "通信中断_s":assignments[r["route_id"]]["interrupted_s"], "覆盖率":assignments[r["route_id"]]["coverage_ratio"],
                   "是否需要中继":assignments[r["route_id"]]["relay_need"], "中继点":assignments[r["route_id"]]["relay"]["name"],
                   "中继经度":assignments[r["route_id"]]["relay"]["lon"], "中继纬度":assignments[r["route_id"]]["relay"]["lat"],
                   "悬停高度_m":assignments[r["route_id"]]["relay"]["height_m"]} for r in routes]).to_csv(os.path.join(OUT,"p3-1_routes.csv"),index=False,encoding="utf-8-sig")
    pd.DataFrame(rows).to_csv(os.path.join(OUT,"p3-1_relay_candidates.csv"),index=False,encoding="utf-8-sig")
    pd.DataFrame(plan["relay_schedule"]).to_csv(os.path.join(OUT,"p3-1_relay_schedule.csv"),index=False,encoding="utf-8-sig")
    timeline=[]
    for r in routes:
        x=relay_map[r["route_id"]]; ts=x.get("transport_start",r["start"]); te=x.get("transport_end",r["end"])
        timeline.append({"资源编号":r["uav_id"],"资源类型":"运输无人机","任务编号":r["sortie_id"],"活动":"运输架次","开始_s":ts,"结束_s":te})
    for x in plan["relay_schedule"]:
        if x["relay_id"]!="无需中继":
            timeline.append({"资源编号":x["relay_id"],"资源类型":"中继无人机","任务编号":x["route_id"],"活动":"中继飞行与服务","开始_s":x["start"],"结束_s":x["end"]})
            timeline.append({"资源编号":x["battery_id"],"资源类型":"中继能源组件","任务编号":x["route_id"],"活动":"充电周转","开始_s":x["end"],"结束_s":x["end"]+float(relay_stock["等效完全充电时间"])})
    pd.DataFrame(timeline).to_csv(os.path.join(OUT,"p3-1_resource_timeline.csv"),index=False,encoding="utf-8-sig")
    comm_rows=[]
    for r in routes:
        a=assignments[r["route_id"]]
        for k,s in enumerate(a["states"]): comm_rows.append({"架次编号":r["sortie_id"],"路线编号":r["route_id"],"采样点序号":k,"通信状态":s,"相对时间_s":k*r["T_route_s"]/max(len(a["states"])-1,1)})
    pd.DataFrame(comm_rows).to_csv(os.path.join(OUT,"p3-1_communication_states.csv"),index=False,encoding="utf-8-sig")
    pd.DataFrame([{"货箱编号":bid,"预测送达_s":t} for bid,t in plan["deliveries"].items()]).to_csv(os.path.join(OUT,"p3-1_box_delivery.csv"),index=False,encoding="utf-8-sig")
    pareto = pd.DataFrame([{"方案":"枚举筛选最优","及时性":plan["f"][0],"联合完成_s":plan["f"][1],"总能耗_kWh":plan["f"][2],"运输架次":plan["f"][3],"中继架次":plan["f"][4],"通信中断_s":plan["f"][5],"硬时限违反_s":plan["f"][6]}])
    pareto.to_csv(os.path.join(OUT,"p3-1_pareto_front.csv"),index=False,encoding="utf-8-sig")
    summary = ["问题三 p3-1：候选中继点枚举筛选", f"运输路线数：{len(routes)}", f"候选点-高度组合：{len(candidates)}",
               f"通信中断总时长(s)：{plan['f'][5]:.2f}", f"硬时限违反量(s)：{plan['f'][6]:.2f}",
               f"联合完成时间(s)：{plan['f'][1]:.2f}", f"运输能耗(kWh)：{plan['transport_energy']:.3f}", f"中继能耗(kWh)：{plan['relay_energy']:.3f}",
               f"运输架次：{plan['f'][3]}；启用中继架次：{plan['f'][4]}", f"中继资源冲突数：{len(plan['relay_bad'])}",
               "可行性判定：通信中断=0、硬时限违反=0且中继资源无冲突时为可行。"]
    with open(os.path.join(OUT,"p3-1_summary.txt"),"w",encoding="utf-8") as f: f.write("\n".join(summary))
    save_basic_figures(FIG,"p3-1",routes,assignments,plan["relay_schedule"],o01,services,boxes,plan,node_map)
    print("\n".join(summary))


if __name__ == "__main__": main()

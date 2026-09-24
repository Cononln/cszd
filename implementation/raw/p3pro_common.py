# -*- coding: utf-8 -*-
"""p3-3pro/p3-4pro共享：通信感知路线顺序与鲁棒中继评价。"""
import os, copy
from itertools import permutations
import numpy as np
import pandas as pd

from q00 import load_nodes, load_transport_drone, load_relay_drone, load_comm_params
from p3_common import (ROOT, read_base_solution, load_dem_array, _comm_budget, make_node_map,
                       candidate_relays, coverage_for_route, relay_energy, evaluate_plan,
                       save_basic_figures)
from q2_common import load_leg_geometry_table, evaluate_route


def load_p3_base(source="p3-1"):
    routes, _, boxes = read_base_solution("q2_1")
    p3dir = os.path.join(ROOT, source, "outputs")
    rdf = pd.read_csv(os.path.join(p3dir, f"{source}_routes.csv"), encoding="utf-8-sig")
    idx = rdf.set_index("路线编号").to_dict("index")
    for r in routes:
        if r["route_id"] in idx:
            x = idx[r["route_id"]]
            r["start"] = float(x["起飞_s"]); r["end"] = float(x["返航_s"])
            r["stops"] = [z for z in str(x["停靠序列"]).split("->") if z != "O01"]
            r["sortie_id"] = str(x["架次编号"]); r["uav_id"] = str(r.get("uav_id", ""))
    return routes, boxes


def candidate_pool(routes, o01, services, arr, transform, n_each=14):
    """优先使用p3-1已筛选的候选点，确保pro方法和基准口径一致。"""
    path = os.path.join(ROOT, "p3-1", "outputs", "p3-1_relay_candidates.csv")
    pool = {}
    if os.path.exists(path):
        d = pd.read_csv(path, encoding="utf-8-sig")
        for rid, g in d.groupby("路线编号"):
            seen=set(); rows=[]
            for _, x in g.sort_values("候选排名").iterrows():
                key=(round(float(x["经度"]),7),round(float(x["纬度"]),7),round(float(x["悬停高度_m"]),1))
                if key not in seen:
                    seen.add(key); rows.append({"relay_id":f"PRO-{rid}-{len(rows)+1:03d}","name":str(x["中继点"]),"lon":key[0],"lat":key[1],"height_m":key[2]})
                if len(rows)>=n_each: break
            pool[str(rid)]=rows
    allc = candidate_relays(routes,o01,services)
    for r in routes:
        pool.setdefault(r["route_id"], allc[:n_each])
    return pool


def route_variants(routes, leg_geo, specs, node_map, budget, arr, transform, o01, relay_spec, pool):
    """对多站路线枚举访问顺序，联合比较能耗和通信覆盖。"""
    out=[]
    for base in routes:
        spec = specs[specs["机型编号"]==base["机型编号"]].iloc[0]
        orders=list(permutations(base["stops"])) if len(base["stops"])>1 else [tuple(base["stops"])]
        best=None
        for order in orders:
            try:
                ev=evaluate_route(order,base["boxes_by_stop"],spec,leg_geo)
            except Exception:
                continue
            if not ev.get("feasible",False): continue
            rr=copy.deepcopy(base); rr["stops"]=list(order); rr["E_route_kWh"]=ev["E_route_kWh"]; rr["T_route_s"]=ev["T_route_s"]
            rr["end"]=rr["start"]+rr["T_route_s"]
            candidates=[]
            for p in pool.get(base["route_id"],[]):
                cov=coverage_for_route(rr,p,node_map,budget,arr,transform)
                e=relay_energy(relay_spec,p,o01,rr["T_route_s"]+float(relay_spec["建链时间"]))[0] if cov["relay_need"] else 0.0
                candidates.append((cov,p,e))
            candidates.sort(key=lambda z:(z[0]["interrupted_s"],z[2],z[0]["relay_need"],rr["E_route_kWh"]))
            cov,p,e=candidates[0]
            key=(cov["interrupted_s"],rr["E_route_kWh"]+e,rr["T_route_s"],int(cov["relay_need"]))
            if best is None or key<best[0]: best=(key,rr,cov,p,e)
        if best is None:
            rr=copy.deepcopy(base); cov=coverage_for_route(rr,pool[base["route_id"]][0],node_map,budget,arr,transform); best=((1e9,1e9,1e9,1),rr,cov,pool[base["route_id"]][0],0.0)
        _,rr,cov,p,e=best; rr["_coverage"]=cov; rr["_relay"]=p; rr["_relay_energy"]=e; out.append(rr)
    return out


def assignment_from_routes(routes):
    return {r["route_id"]:{**r["_coverage"],"relay":r["_relay"],"relay_energy":r["_relay_energy"]} for r in routes}


def write_p3_outputs(tag, outdir, routes, plan, boxes, scenario_rows=None):
    os.makedirs(outdir,exist_ok=True)
    rows=[]
    for r in routes:
        a=r["_coverage"]; p=r["_relay"]
        rows.append({"路线编号":r["route_id"],"架次编号":r.get("sortie_id",r["route_id"]),"机型编号":r["机型编号"],"停靠序列":"O01->"+"->".join(r["stops"])+"->O01","起飞_s":r["start"],"返航_s":r["end"],"通信中断_s":a["interrupted_s"],"覆盖率":a["coverage_ratio"],"是否需要中继":a["relay_need"],"中继点":p["name"],"中继经度":p["lon"],"中继纬度":p["lat"],"悬停高度_m":p["height_m"],"路线能耗_kWh":r["E_route_kWh"],"路线时间_s":r["T_route_s"]})
    pd.DataFrame(rows).to_csv(os.path.join(outdir,f"{tag}_routes.csv"),index=False,encoding="utf-8-sig")
    pd.DataFrame(plan["relay_schedule"]).to_csv(os.path.join(outdir,f"{tag}_relay_schedule.csv"),index=False,encoding="utf-8-sig")
    cs=[]
    for r in routes:
        for j,s in enumerate(r["_coverage"]["states"]): cs.append({"架次编号":r.get("sortie_id",r["route_id"]),"路线编号":r["route_id"],"采样点序号":j,"通信状态":s,"相对时间_s":j*r["T_route_s"]/max(len(r["_coverage"]["states"])-1,1)})
    pd.DataFrame(cs).to_csv(os.path.join(outdir,f"{tag}_communication_states.csv"),index=False,encoding="utf-8-sig")
    pd.DataFrame([{"货箱编号":bid,"预测送达_s":t} for bid,t in plan["deliveries"].items()]).to_csv(os.path.join(outdir,f"{tag}_box_delivery.csv"),index=False,encoding="utf-8-sig")
    if scenario_rows is not None: pd.DataFrame(scenario_rows).to_csv(os.path.join(outdir,f"{tag}_scenario_evaluation.csv"),index=False,encoding="utf-8-sig")


def prepare_context():
    routes,boxes=load_p3_base("p3-1"); o01,services=load_nodes(); arr,transform,_=load_dem_array(); budget=_comm_budget(load_comm_params()); node_map=make_node_map(o01,services); specs,_,_=load_transport_drone(); rspec_df,rfleet,rstock=load_relay_drone(); return routes,boxes,o01,services,arr,transform,budget,node_map,specs,rspec_df.iloc[0],rfleet,rstock.iloc[0]

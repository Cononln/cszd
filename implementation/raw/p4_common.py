# -*- coding: utf-8 -*-
"""问题四共享模块：固定问题三调度下的任务分区与资源核算。"""
import os
import math
from itertools import product
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from q00 import load_nodes, load_transport_drone, load_relay_drone, style_ax, CAT, DRONE_COLOR, INK, MUTED, GRID, BASELINE, SURFACE
from q2_common import charge_time

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_fixed_plan(source="p3-1"):
    """读取问题三输出，并补齐问题二架次中的运输无人机/电池标识。"""
    p3dir = os.path.join(ROOT, source, "outputs")
    p3 = pd.read_csv(os.path.join(p3dir, f"{source}_routes.csv"), encoding="utf-8-sig")
    relay = pd.read_csv(os.path.join(p3dir, f"{source}_relay_schedule.csv"), encoding="utf-8-sig")
    q2routes = pd.read_csv(os.path.join(ROOT, "q2_1_routes.csv"), encoding="utf-8-sig")
    q2sorties = pd.read_csv(os.path.join(ROOT, "q2_1_sorties.csv"), encoding="utf-8-sig")
    q2r = q2routes.set_index("路线编号").to_dict("index")
    q2s = q2sorties.set_index("架次编号").to_dict("index")
    routes = []
    for _, row in p3.iterrows():
        rid = row["路线编号"]; tid = row["架次编号"]
        q2a = q2r.get(rid, {}); q2b = q2s.get(tid, {})
        stops = [x for x in str(row["停靠序列"]).split("->") if x != "O01"]
        routes.append({
            "route_id": rid, "sortie_id": tid, "stops": stops,
            "type": str(row["机型编号"]), "start": float(row["起飞_s"]), "end": float(row["返航_s"]),
            "uav_id": str(q2b.get("无人机编号", "unknown")), "battery_id": str(q2b.get("电池编号", "unknown")),
            "energy": float(q2a.get("E_route_kWh", 0.0)), "box_count": int(float(q2a.get("箱数", 0))),
            "mass": float(q2a.get("总质量_kg", 0.0)), "volume": float(q2a.get("总体积_m3", 0.0)),
        })
    relay_map = {str(x["route_id"]): x for _, x in relay.iterrows()}
    for r in routes:
        x = relay_map.get(str(r["route_id"]), None)
        if x is None or str(x["relay_id"]) == "无需中继":
            r.update({"relay": False, "relay_id": "", "relay_battery": "", "relay_start": None,
                      "relay_end": None, "relay_energy": 0.0})
        else:
            r.update({"relay": True, "relay_id": str(x["relay_id"]), "relay_battery": str(x["battery_id"]),
                      "relay_start": float(x["start"]), "relay_end": float(x["end"]),
                      "relay_energy": float(x["energy_kWh"])})
    return routes


def build_components(routes, services):
    """由同一运输架次的停靠序列构造冲突图连通分量。"""
    parent = {str(x): str(x) for x in services["服务区编号"]}
    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x: parent[x] = find(parent[x])
        return parent[x]
    def union(a, b):
        a, b = find(a), find(b)
        if a != b: parent[b] = a
    for r in routes:
        st = r["stops"]
        for x in st: find(x)
        for a, b in zip(st[:-1], st[1:]): union(a, b)
    comps = defaultdict(list)
    for x in parent: comps[find(x)].append(x)
    comps = [sorted(v) for v in comps.values()]
    comps.sort(key=lambda x: x[0])
    comp_of = {x: i for i, c in enumerate(comps) for x in c}
    for r in routes: r["component"] = comp_of[r["stops"][0]] if r["stops"] else -1
    return comps, comp_of


def overlap_peak(intervals):
    """闭开区间最大重叠数，采用事件扫描。"""
    ev = []
    for a, b in intervals:
        if a is None or b is None: continue
        ev.append((float(a), 1)); ev.append((float(b), -1))
    ev.sort(key=lambda z: (z[0], z[1]))
    cur = peak = 0
    for _, d in ev:
        cur += d; peak = max(peak, cur)
    return peak


def resource_events(routes, group_of, transport_spec, transport_batt, relay_spec, relay_stock):
    """核算每组运输/中继资源峰值需求。"""
    e = defaultdict(list)
    spec = transport_spec.set_index("机型编号").to_dict("index")
    batt = transport_batt.set_index("机型编号").to_dict("index")
    for r in routes:
        g = group_of[r["component"]]
        typ = r["type"]
        e[(g, f"运输无人机_{typ}")].append((r["start"], r["end"]))
        tcharge = charge_time(1.0 - r["energy"] / max(float(spec[typ]["电池可用能量"]), 1e-9),
                              float(batt[typ]["等效完全充电时间"]))
        e[(g, f"共享电池_{typ}")].append((r["start"], r["end"] + tcharge))
        if r["relay"]:
            e[(g, "中继无人机")].append((r["relay_start"], r["relay_end"]))
            soc_ratio = r["relay_energy"] / max(float(relay_spec["能源组件可用能量"]), 1e-9)
            relay_charge = float(relay_stock["等效完全充电时间"]) * min(1.0, max(0.0, soc_ratio))
            e[(g, "中继能源组件")].append((r["relay_end"], r["relay_end"] + relay_charge))
    return {key: overlap_peak(v) for key, v in e.items()}


def inventory(transport_spec, transport_batt, relay_fleet, relay_stock):
    inv = {}
    for _, x in transport_spec.iterrows(): inv[f"运输无人机_{x['机型编号']}"] = int((relay_fleet["机型编号"] == x["机型编号"]).sum()) if "机型编号" in relay_fleet else 0
    # 上行写法不依赖机队表列位置，重新按机型统计运输机库存。
    return inv


def get_inventory(transport_fleet, transport_batt, relay_fleet, relay_stock):
    inv = {}
    for typ, sub in transport_fleet.groupby("机型编号"): inv[f"运输无人机_{typ}"] = int(len(sub))
    for _, x in transport_batt.iterrows(): inv[f"共享电池_{x['机型编号']}"] = int(float(x["共享电池组总数"]))
    inv["中继无人机"] = int(len(relay_fleet))
    inv["中继能源组件"] = int(float(relay_stock["共享能源组件总数"]))
    return inv


def workload(routes, group_of):
    out = defaultdict(lambda: {"服务区": set(), "架次": 0, "箱数": 0, "质量_kg": 0.0,
                               "运输能耗_kWh": 0.0, "中继能耗_kWh": 0.0, "作业时长_s": 0.0})
    for r in routes:
        g = group_of[r["component"]]; x = out[g]
        x["服务区"].update(r["stops"]); x["架次"] += 1; x["箱数"] += r["box_count"]
        x["质量_kg"] += r["mass"]; x["运输能耗_kWh"] += r["energy"]; x["中继能耗_kWh"] += r["relay_energy"]
        x["作业时长_s"] += r["end"] - r["start"]
    for x in out.values(): x["服务区"] = "、".join(sorted(x["服务区"]))
    return dict(out)


def evaluate_partition(routes, assignment, k, transport_spec, transport_fleet, transport_batt, relay_spec, relay_fleet, relay_stock, components):
    group_of = {i: int(assignment[i]) for i in range(len(components))}
    needs = resource_events(routes, group_of, transport_spec, transport_batt, relay_spec, relay_stock)
    inv = get_inventory(transport_fleet, transport_batt, relay_fleet, relay_stock)
    need_names = {key for _, key in needs}
    all_keys = sorted(set(inv) | need_names)
    total_need = sum(needs.get((g, key), 0) for g in range(k) for key in all_keys)
    gap = sum(max(0, needs.get((g, key), 0) - inv.get(key, 0)) for g in range(k) for key in all_keys)
    group_need = {g: sum(v for (gg, _), v in needs.items() if gg == g) for g in range(k)}
    w = workload(routes, group_of)
    wvals = np.array([sum([v["作业时长_s"] / 3600.0, v["运输能耗_kWh"], v["箱数"] * 0.1]) for v in w.values()])
    balance = float(np.std(wvals) / max(np.mean(wvals), 1e-9)) if len(wvals) else 0.0
    redundancy = sum(max(0, inv.get(key, 0) - needs.get(key, 0)) for key in all_keys)
    score = (gap, total_need, balance, redundancy)
    return {"assignment": tuple(assignment), "group_of": group_of, "needs": needs, "inventory": inv,
            "gap": gap, "total_need": total_need, "balance": balance, "redundancy": redundancy,
            "score": score, "workload": w, "group_need": group_need}


def all_partitions(n, k):
    """生成不重复的无标签分区编码（restricted growth string）。"""
    if n <= 0: return
    a = [0] * n
    def rec(pos, max_label):
        if pos == n:
            if max_label == k - 1: yield tuple(a)
            return
        for g in range(min(max_label + 2, k)):
            a[pos] = g
            yield from rec(pos + 1, max(max_label, g))
    yield from rec(1, 0)


def normalize_label(assignment):
    """消除组编号置换，便于保存结果。"""
    mp = {}; nxt = 0; out=[]
    for x in assignment:
        if x not in mp: mp[x] = nxt; nxt += 1
        out.append(mp[x])
    return tuple(out)


def partition_rows(plan, components, k):
    rows=[]
    for i, c in enumerate(components): rows.append({"任务组": int(plan["assignment"][i])+1, "任务块编号": i+1, "服务区列表": "、".join(c)})
    return rows


def resource_rows(plan, k):
    rows=[]
    need_names={key for _,key in plan["needs"]}
    for key in sorted(set(plan["inventory"]) | need_names):
        for g in range(k):
            need = plan["needs"].get((g,key), 0); stock = plan["inventory"].get(key,0)
            rows.append({"任务组":g+1,"资源":key,"需求数量":need,"现有库存":stock,"组内冗余":max(0,stock-need),"资源缺口":max(0,need-stock)})
    return rows


def workload_rows(plan):
    rows=[]
    for g,x in sorted(plan["workload"].items()): rows.append({"任务组":g+1, **x})
    return rows


def save_figures(out_dir, tag, routes, services, plans, components):
    os.makedirs(out_dir, exist_ok=True)
    colors = [CAT[0], CAT[1], CAT[2], CAT[3], CAT[4]]
    # 地图：上下排列展示2组和3组
    fig, axes = plt.subplots(1,2,figsize=(14,6.2))
    for ax, (k,plan) in zip(axes, sorted(plans.items())):
        comp_of = plan["group_of"]
        svc_group = {s:g for i,c in enumerate(components) for s in c for g in [comp_of[i]]}
        for _, s in services.iterrows():
            g=svc_group.get(str(s["服务区编号"]),0); ax.scatter(s["经度"],s["纬度"],s=75,color=colors[g],edgecolor=INK,zorder=4); ax.text(s["经度"],s["纬度"],str(s["服务区编号"]),fontsize=7,ha="left",va="bottom")
        for r in routes:
            path=["O01"]+r["stops"]+["O01"]; xy=[]
            for p in path:
                if p=="O01": xy.append((services["经度"].mean(),services["纬度"].mean()))
                else:
                    q=services[services["服务区编号"]==p].iloc[0]; xy.append((q["经度"],q["纬度"]))
            g=comp_of[r["component"]]; ax.plot([x[0] for x in xy],[x[1] for x in xy],color=colors[g],alpha=.25,lw=1)
        ax.set_title(f"{tag}：{k}组服务区分区",loc="left",fontweight="bold"); ax.set_xlabel("经度"); ax.set_ylabel("纬度"); style_ax(ax,"both")
        ax.legend(handles=[Patch(color=colors[i],label=f"任务组{i+1}") for i in range(k)],frameon=False,fontsize=8)
    fig.savefig(os.path.join(out_dir,f"{tag}_01_分区地图.png"),bbox_inches="tight",facecolor=SURFACE,dpi=180); plt.close(fig)
    # 资源需求与库存
    fig, axes=plt.subplots(1,2,figsize=(15,5.5))
    for ax,(k,plan) in zip(axes, sorted(plans.items())):
        need_names={key for _,key in plan["needs"]}
        keys=sorted(set(plan["inventory"])|need_names); x=np.arange(len(keys)); width=.78/k
        for g in range(k): ax.bar(x+(g-(k-1)/2)*width,[plan["needs"].get((g,key),0) for key in keys],width,label=f"组{g+1}",color=colors[g])
        ax.plot(x,[plan["inventory"].get(key,0) for key in keys],"k--",marker="o",label="现有库存")
        ax.set_xticks(x); ax.set_xticklabels(keys,rotation=35,ha="right",fontsize=8); ax.set_ylabel("数量"); ax.set_title(f"{k}组资源需求与库存",loc="left",fontweight="bold"); style_ax(ax,"y"); ax.legend(frameon=False,fontsize=8)
    fig.savefig(os.path.join(out_dir,f"{tag}_02_资源需求库存.png"),bbox_inches="tight",facecolor=SURFACE,dpi=180); plt.close(fig)
    # 工作量均衡
    fig, ax=plt.subplots(figsize=(9,5)); labels=[]; vals=[]
    for k,plan in sorted(plans.items()):
        for g,x in sorted(plan["workload"].items()): labels.append(f"{k}组-组{g+1}"); vals.append(x["作业时长_s"]/3600+x["运输能耗_kWh"]+x["箱数"]*.1)
    ax.bar(labels,vals,color=[colors[i%len(colors)] for i in range(len(vals))]); ax.set_ylabel("归一化工作量"); ax.set_title(f"{tag} 任务组工作量比较",loc="left",fontweight="bold"); ax.tick_params(axis="x",rotation=25); style_ax(ax,"y"); fig.savefig(os.path.join(out_dir,f"{tag}_03_工作量均衡.png"),bbox_inches="tight",facecolor=SURFACE,dpi=180); plt.close(fig)
    # 缺口冗余
    fig, ax=plt.subplots(figsize=(10,5)); labels=[]; gaps=[]; reds=[]
    for k,plan in sorted(plans.items()): labels.append(f"{k}组"); gaps.append(plan["gap"]); reds.append(plan["redundancy"])
    x=np.arange(len(labels)); ax.bar(x,gaps,label="资源缺口",color="#d94b4b"); ax.bar(x,reds,bottom=gaps,label="组内冗余",color=CAT[3]); ax.set_xticks(x,labels); ax.set_ylabel("资源数量"); ax.set_title(f"{tag} 资源缺口与冗余",loc="left",fontweight="bold"); style_ax(ax,"y"); ax.legend(frameon=False); fig.savefig(os.path.join(out_dir,f"{tag}_04_缺口冗余.png"),bbox_inches="tight",facecolor=SURFACE,dpi=180); plt.close(fig)

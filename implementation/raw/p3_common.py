# -*- coding: utf-8 -*-
"""问题三共享组件：通信覆盖、候选中继点和联合资源排程。

本文件为 p3-1（候选点枚举筛选）和 p3-2（随机局部搜索）提供公共函数，
不修改问题一、问题二的任何代码或结果。
"""
import math
import os
import heapq
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import rasterio

from q00 import (load_nodes, load_box_list, load_transport_drone, load_relay_drone,
                 load_comm_params, F_DEM_TIF, planar_distance_km, style_ax, savefig,
                 SURFACE, INK, INK2, MUTED, GRID, BASELINE, CAT, DRONE_COLOR)
from q2_common import hard_deadline

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "无人机应急物资运输基础数据")
Q2_DIR = ROOT


def read_base_solution(prefix="q2_1"):
    """读取问题二代表路线/架次，并恢复为可计算的字典结构。"""
    routes_df = pd.read_csv(os.path.join(Q2_DIR, f"{prefix}_routes.csv"), encoding="utf-8-sig")
    sorties_df = pd.read_csv(os.path.join(Q2_DIR, f"{prefix}_sorties.csv"), encoding="utf-8-sig")
    boxes = load_box_list()
    box_dict = {r["货箱编号"]: r for r in boxes.to_dict("records")}
    routes = []
    for i, row in routes_df.iterrows():
        path = str(row["停靠序列"]).split("->")
        stops = [x for x in path if x != "O01"]
        ids = [x for x in str(row["货箱列表"]).split("|") if x and x != "nan"]
        by_stop = defaultdict(list)
        for bid in ids:
            if bid in box_dict:
                by_stop[box_dict[bid]["服务区编号"]].append(box_dict[bid])
        routes.append({
            "route_id": f"R{i+1:03d}", "机型编号": str(row["机型编号"]),
            "stops": stops, "boxes_by_stop": dict(by_stop),
            "E_route_kWh": float(row["E_route_kWh"]), "T_route_s": float(row["T_route_s"]),
            "货箱列表": ids,
        })
    # 同一路线结构可能重复，用出现顺序匹配问题二架次。
    queues = defaultdict(list)
    for r in routes:
        queues[(r["机型编号"], "O01->" + "->".join(r["stops"]) + "->O01")].append(r)
    sorties = []
    for i, row in sorties_df.iterrows():
        key = (str(row["机型编号"]), str(row["停靠序列"]))
        r = queues[key].pop(0) if queues[key] else None
        if r is None:
            # 容错：根据路径匹配任意剩余路线
            r = next((x for x in routes if x.get("_used") is not True and x["机型编号"] == str(row["机型编号"])
                      and "->".join(["O01"] + x["stops"] + ["O01"]) == str(row["停靠序列"])), routes[0])
        r["_used"] = True
        r["sortie_id"] = str(row["架次编号"])
        r["uav_id"] = str(row["无人机编号"])
        r["battery_id"] = str(row["电池编号"])
        r["start"] = float(row["起飞时刻_s"])
        r["end"] = float(row["返航时刻_s"])
        sorties.append(r)
    # 若存在未匹配路线，安排在问题二末尾串行执行，确保80箱仍被覆盖。
    next_t = max((r["end"] for r in sorties), default=0.0)
    for r in routes:
        if "start" not in r:
            r["sortie_id"] = f"T{len(sorties)+1:03d}"
            r["uav_id"] = "unassigned"
            r["battery_id"] = "unassigned"
            r["start"] = next_t
            r["end"] = next_t + r["T_route_s"]
            next_t = r["end"]
            sorties.append(r)
    for r in routes:
        r.pop("_used", None)
    return routes, sorties, boxes


def load_dem_array():
    with rasterio.open(F_DEM_TIF) as src:
        return src.read(1), src.transform, src.bounds


def _comm_budget(comm):
    def val(pattern):
        return float(comm.loc[comm["参数名称"].str.contains(pattern), "参数值"].iloc[0])
    lsys, lobs = val("系统损耗"), val("地形遮挡")
    pth = val("接收灵敏度") + val("衰落裕量")
    def role(cat):
        s = comm[comm["参数类别"] == cat]
        return float(s.loc[s["参数名称"].str.contains("发射功率"), "参数值"].iloc[0]), \
               float(s.loc[s["参数名称"].str.contains("天线增益"), "参数值"].iloc[0])
    uav = role("运输无人机"); acc = role("中继接入端"); bh = role("中继回传端"); gw = role("固定网关 G01")
    # 双向链路取最小预算，附加地形损耗单独判断。
    return {"direct": min(uav[0] + uav[1] + gw[1], gw[0] + gw[1] + uav[1]) - lsys - pth,
            "access": min(uav[0] + uav[1] + acc[1], acc[0] + acc[1] + uav[1]) - lsys - pth,
            "backhaul": min(bh[0] + bh[1] + gw[1], gw[0] + gw[1] + bh[1]) - lsys - pth,
            "lobs": lobs, "freq_mhz": val("载波频率")}


def fspl_db(distance_m, freq_mhz):
    d_km = max(distance_m / 1000.0, 0.001)
    return 32.44 + 20.0 * math.log10(d_km) + 20.0 * math.log10(freq_mhz)


def ground_elevation(arr, transform, lon, lat):
    try:
        c, r = (~transform) * (lon, lat)
        c, r = int(round(c)), int(round(r))
        if 0 <= r < arr.shape[0] and 0 <= c < arr.shape[1]:
            return float(arr[r, c])
    except Exception:
        pass
    return 0.0


def blocked_by_terrain(a, b, arr, transform, n=12):
    """端点高度为绝对海拔时，检查中间地面是否超过视线（留2m余量）。"""
    if arr is None:
        return False
    za, zb = a[2], b[2]
    for t in np.linspace(0.08, 0.92, n):
        lon = a[0] + t * (b[0] - a[0]); lat = a[1] + t * (b[1] - a[1])
        zg = ground_elevation(arr, transform, lon, lat)
        zline = za + t * (zb - za)
        if zg > zline - 2.0:
            return True
    return False


def link_ok(a, b, budget, arr, transform):
    d = planar_distance_km(a[0], a[1], b[0], b[1]) * 1000.0
    loss = fspl_db(d, budget["freq_mhz"])
    terrain = blocked_by_terrain(a, b, arr, transform)
    return loss + (budget["lobs"] if terrain else 0.0) <= budget["direct"] + 1e-9, d, loss, terrain


def make_node_map(o01, services):
    m = {"O01": (float(o01["经度"]), float(o01["纬度"]), float(o01["海拔"]) + 20.0)}
    for _, s in services.iterrows():
        m[str(s["服务区编号"])] = (float(s["经度"]), float(s["纬度"]), float(s["海拔"]) + 20.0)
    return m


def candidate_relays(routes, o01, services, heights=(80, 160, 240, 300)):
    """沿服务区和路线中点生成去重的中继悬停候选。"""
    nm = make_node_map(o01, services)
    pts = [("O01", nm["O01"][0], nm["O01"][1])]
    for _, s in services.iterrows():
        pts.append((str(s["服务区编号"]), float(s["经度"]), float(s["纬度"])))
    for r in routes:
        path = ["O01"] + r["stops"] + ["O01"]
        for a, b in zip(path[:-1], path[1:]):
            pa, pb = nm[a], nm[b]
            for t in (0.35, 0.5, 0.65):
                pts.append((f"{a}-{b}-{t:.2f}", pa[0] + t*(pb[0]-pa[0]), pa[1] + t*(pb[1]-pa[1])))
    # 小网格扩展，降低因地形遮挡而无候选的概率
    lon0, lon1 = services["经度"].min(), services["经度"].max()
    lat0, lat1 = services["纬度"].min(), services["纬度"].max()
    for i, lo in enumerate(np.linspace(lon0, lon1, 4)):
        for j, la in enumerate(np.linspace(lat0, lat1, 4)):
            pts.append((f"grid-{i}-{j}", float(lo), float(la)))
    out, seen = [], set()
    for name, lo, la in pts:
        key = (round(lo, 6), round(la, 6))
        if key in seen: continue
        seen.add(key)
        for h in heights:
            out.append({"relay_id": f"RLY-{len(out)+1:03d}", "name": name,
                        "lon": lo, "lat": la, "height_m": float(h)})
    return out


def route_path_samples(route, node_map, n_per_leg=7):
    pts = []
    path = ["O01"] + route["stops"] + ["O01"]
    for a, b in zip(path[:-1], path[1:]):
        pa, pb = node_map[a], node_map[b]
        for t in np.linspace(0, 1, n_per_leg, endpoint=False):
            pts.append((pa[0] + t*(pb[0]-pa[0]), pa[1] + t*(pb[1]-pa[1]),
                        pa[2] + t*(pb[2]-pa[2]) + 40.0))
    pb = node_map[path[-1]]
    pts.append((pb[0], pb[1], pb[2] + 40.0))
    return pts


def coverage_for_route(route, relay, node_map, budget, arr, transform):
    """返回逐采样点直连/中继状态以及中断秒数（中继候选覆盖整个架次才有效）。"""
    samples = route_path_samples(route, node_map)
    # 运输航段巡航高度按“航段最高地面高程+净空”确定。用每一条路线的
    # 采样地面最高值修正高度，避免把服务区端点海拔误当成整条航线高度，
    # 从而正确覆盖爬升/巡航/下降阶段的视距判定。
    path = ["O01"] + route["stops"] + ["O01"]
    ground_max = 0.0
    if arr is not None:
        for a, b in zip(path[:-1], path[1:]):
            pa, pb = node_map[a], node_map[b]
            for t in np.linspace(0.0, 1.0, 15):
                ground_max = max(ground_max, ground_elevation(arr, transform,
                    pa[0] + t*(pb[0]-pa[0]), pa[1] + t*(pb[1]-pa[1])))
    cruise_z = max(ground_max + 50.0, max(p[2] for p in samples))
    samples = [(p[0], p[1], cruise_z) for p in samples]
    states = []
    for p in samples:
        g = (node_map["O01"][0], node_map["O01"][1], node_map["O01"][2] + 20.0)
        direct, _, _, _ = link_ok(p, g, budget, arr, transform)
        rp = (relay["lon"], relay["lat"], relay["height_m"] + ground_elevation(arr, transform, relay["lon"], relay["lat"]))
        access, _, _, _ = link_ok(p, rp, {**budget, "direct": budget["access"]}, arr, transform)
        back, _, _, _ = link_ok(rp, g, {**budget, "direct": budget["backhaul"]}, arr, transform)
        states.append("直连" if direct else ("中继" if access and back else "中断"))
    # 近似按路线飞行时间均匀映射采样点；仅将通信中断计为硬约束。
    dt = route["T_route_s"] / max(len(states)-1, 1)
    interrupted = sum(s == "中断" for s in states) * dt
    relay_need = any(s == "中继" for s in states)
    return {"states": states, "interrupted_s": float(interrupted), "relay_need": relay_need,
            "samples": samples, "coverage_ratio": 1.0 - interrupted / max(route["T_route_s"], 1.0)}


def relay_energy(relay_spec, point, o01, service_s):
    d = planar_distance_km(o01["经度"], o01["纬度"], point["lon"], point["lat"]) * 1000.0
    climb = max(point["height_m"], 0.0) / max(float(relay_spec["最大爬升速度"]), 1.0)
    desc = max(point["height_m"], 0.0) / max(float(relay_spec["最大下降速度"]), 1.0)
    fly = 2.0 * d / max(float(relay_spec["计划巡航速度"]), 1.0)
    pcruise = float(relay_spec["巡航功率"]); phover = float(relay_spec["悬停功率"] + relay_spec["通信附加功率"])
    e = (fly/3600.0)*pcruise + ((climb+desc)/3600.0)*phover + (service_s/3600.0)*phover
    return e, 2*d/max(float(relay_spec["计划巡航速度"]), 1.0) + climb + desc + service_s


def schedule_relays(routes, assignments, relay_spec, relay_fleet, relay_stock, o01):
    """按运输架次时间排程中继机和能源组件，返回联合架次与可行性。"""
    n_relay = max(1, len(relay_fleet)); n_batt = max(1, int(relay_stock["共享能源组件总数"]))
    rheap = [(0.0, str(relay_fleet.iloc[i]["中继无人机编号"])) for i in range(n_relay)]
    bheap = [(0.0, f"R-电池{i+1:02d}") for i in range(n_batt)]
    heapq.heapify(rheap); heapq.heapify(bheap)
    out, infeasible = [], []
    for r in sorted(routes, key=lambda x: x["start"]):
        a = assignments[r["route_id"]]
        if not a["relay_need"]:
            out.append({"route_id": r["route_id"], "relay_id": "无需中继", "battery_id": "无需中继",
                        "start": r["start"], "service_start": r["start"], "service_end": r["end"],
                        "end": r["end"], "energy_kWh": 0.0, "delay_s": 0.0})
            continue
        point = a["relay"]
        e, travel_s = relay_energy(relay_spec, point, o01, r["T_route_s"] + float(relay_spec["建链时间"]))
        rr, rid = heapq.heappop(rheap); bb, bid = heapq.heappop(bheap)
        # 若共享中继暂不可用，则把对应运输架次整体顺延，保证“中继先就绪、
        # 再起飞”的连续通信约束，而不是把冲突留给结果表。
        build_s = float(relay_spec["建链时间"])
        transport_start = max(r["start"], rr + travel_s/2.0 + build_s)
        service_start = transport_start - build_s
        service_end = transport_start + r["T_route_s"] + build_s
        start = service_start - travel_s/2.0
        end = service_end + travel_s/2.0
        heapq.heappush(rheap, (end + float(relay_spec["架次周转时间"]), rid))
        soc = e / max(float(relay_spec["能源组件可用能量"]), 1e-6)
        charge = float(relay_stock["等效完全充电时间"]) * min(1.0, max(0.0, soc))
        heapq.heappush(bheap, (end + charge, bid))
        out.append({"route_id": r["route_id"], "relay_id": rid, "battery_id": bid,
                    "start": start, "service_start": service_start, "service_end": service_end,
                    "end": end, "transport_start": transport_start,
                    "transport_end": transport_start + r["T_route_s"],
                    "energy_kWh": e, "delay_s": max(0.0, transport_start-r["start"])})
    return out, infeasible


def evaluate_plan(routes, assignments, relay_spec, relay_fleet, relay_stock, o01, boxes):
    relay_sched, relay_bad = schedule_relays(routes, assignments, relay_spec, relay_fleet, relay_stock, o01)
    rmap = {x["route_id"]: x for x in relay_sched}
    deliveries = {}
    rshift = {x["route_id"]: x.get("transport_start", next(r["start"] for r in routes if r["route_id"] == x["route_id"]))
              for x in relay_sched}
    for r in routes:
        # 运输架次保持问题二时刻；中继不能拖延运输，排程冲突计入惩罚。
        for area, bs in r["boxes_by_stop"].items():
            # 以到达时刻的比例近似首个服务区到达；路线表给出总时长，足以做时限比较
            arr = rshift.get(r["route_id"], r["start"]) + 0.55 * r["T_route_s"]
            for b in bs:
                deliveries[b["货箱编号"]] = arr
    timely = 0.0; violations = 0.0
    for _, b in boxes.iterrows():
        t = deliveries.get(b["货箱编号"], 1e9)
        timely += float(b["应急优先系数"]) * max(0.0, t - float(b["期望送达时间"]))
        hd = hard_deadline(b)
        if hd is not None and t > hd + 1e-6: violations += t - hd
    comm_interrupt = sum(float(a["interrupted_s"]) for a in assignments.values())
    relay_energy_total = sum(x["energy_kWh"] for x in relay_sched)
    transport_energy = sum(float(r["E_route_kWh"]) for r in routes)
    makespan = max([rshift.get(r["route_id"], float(r["end"])) + float(r["T_route_s"]) for r in routes] + [float(x["end"]) for x in relay_sched])
    f = (timely, makespan, transport_energy + relay_energy_total, len(routes),
         sum(1 for a in assignments.values() if a["relay_need"]), comm_interrupt, violations)
    return {"f": f, "relay_schedule": relay_sched, "relay_bad": relay_bad,
            "deliveries": deliveries, "transport_energy": transport_energy,
            "relay_energy": relay_energy_total, "makespan": makespan}


def save_basic_figures(out_dir, tag, routes, assignments, relay_sched, o01, services, boxes, plan, node_map):
    os.makedirs(out_dir, exist_ok=True)
    # 1. 地图：路线和中继点
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.scatter([o01["经度"]], [o01["纬度"]], marker="s", s=180, color=INK, label="O01/G01", zorder=5)
    ax.scatter(services["经度"], services["纬度"], s=55, color=MUTED, label="服务区", zorder=3)
    nm = node_map
    for _, s in services.iterrows(): ax.annotate(s["服务区编号"], (s["经度"], s["纬度"]), fontsize=7)
    for r in routes:
        path=["O01"]+r["stops"]+["O01"]; xy=[nm[x] for x in path]
        ax.plot([p[0] for p in xy], [p[1] for p in xy], color=DRONE_COLOR.get(r["机型编号"], CAT[0]), alpha=.35, lw=1.1)
    used = set()
    for a in assignments.values():
        if a["relay_need"]:
            p=a["relay"]; key=(p["lon"],p["lat"])
            if key not in used:
                ax.scatter([p["lon"]],[p["lat"]], marker="^", s=95, color=CAT[3], edgecolor=INK, label="中继悬停点" if not used else None, zorder=6)
                ax.text(p["lon"],p["lat"],f'{p["height_m"]:.0f}m',fontsize=7)
                used.add(key)
    style_ax(ax, "both"); ax.set_xlabel("经度"); ax.set_ylabel("纬度"); ax.set_title(f"{tag} 运输路线与中继悬停点", loc="left", fontweight="bold"); ax.legend(frameon=False, fontsize=8)
    savefig(fig, os.path.join(out_dir, f"{tag}_01_路线中继地图.png"))
    # 2. 通信状态热图
    fig, ax = plt.subplots(figsize=(12, max(4, .26*len(routes)+2)))
    cmap={"直连":CAT[2],"中继":CAT[3],"中断":"#d94b4b"}
    for i,r in enumerate(routes):
        st=assignments[r["route_id"]]["states"]; w=r["T_route_s"]/max(len(st),1)
        for j,s in enumerate(st): ax.barh(i, w/60, left=j*w/60, color=cmap[s], height=.72)
    ax.set_yticks(range(len(routes))); ax.set_yticklabels([r["route_id"] for r in routes]); ax.set_xlabel("架次内相对时间 (min)"); ax.set_title(f"{tag} 连续通信状态", loc="left", fontweight="bold"); style_ax(ax,"x")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=cmap[x],label=x) for x in cmap], frameon=False, ncol=3)
    savefig(fig, os.path.join(out_dir, f"{tag}_02_通信状态时间轴.png"))
    # 3. 联合甘特
    fig, ax = plt.subplots(figsize=(12, 7)); rows=[]; events=[]
    for r in routes: rows.append(r["sortie_id"]); events.append((r["sortie_id"],r["start"],r["end"],CAT[0],"运输"))
    for x in relay_sched:
        if x["relay_id"]!="无需中继": rows.append(x["relay_id"]); events.append((x["relay_id"],x["start"],x["end"],CAT[3],"中继"))
    yy={y:i for i,y in enumerate(dict.fromkeys(rows))}
    for rid,s,e,c,label in events: ax.barh(yy[rid],(e-s)/3600,left=s/3600,color=c,height=.6,label=label)
    ax.set_yticks(list(yy.values())); ax.set_yticklabels(list(yy.keys())); ax.set_xlabel("时间 (h)"); ax.set_title(f"{tag} 运输—中继联合甘特图",loc="left",fontweight="bold"); style_ax(ax,"x")
    hs=[]; seen=set()
    for c,l in [(CAT[0],"运输"),(CAT[3],"中继")]:
        if l not in seen: hs.append(plt.Rectangle((0,0),1,1,color=c,label=l)); seen.add(l)
    ax.legend(handles=hs,frameon=False); savefig(fig,os.path.join(out_dir,f"{tag}_03_联合甘特图.png"))
    # 4. 能耗和通信比例
    fig, axes=plt.subplots(1,2,figsize=(11,4.5))
    axes[0].bar(["运输","中继"],[plan["transport_energy"],plan["relay_energy"]],color=[CAT[0],CAT[3]]); axes[0].set_ylabel("能耗 (kWh)"); axes[0].set_title("分项能耗"); style_ax(axes[0],"y")
    counts=[sum(a["states"].count(k) for a in assignments.values()) for k in ("直连","中继","中断")]
    axes[1].pie(counts,labels=["直连","中继","中断"],colors=[CAT[2],CAT[3],"#d94b4b"],autopct="%1.1f%%",startangle=90); axes[1].set_title("通信状态占比")
    savefig(fig,os.path.join(out_dir,f"{tag}_04_能耗通信构成.png"))
    # 5. 逐箱时限图
    fig, ax=plt.subplots(figsize=(12,5)); rec=[]
    for _,b in boxes.iterrows():
        t=plan["deliveries"].get(b["货箱编号"],np.nan); rec.append((b["货箱编号"],t,float(b["期望送达时间"]),b["物资类型"]))
    rec=rec[:]
    x=np.arange(len(rec)); ax.scatter(x,[z[2]/3600 for z in rec],s=14,color=CAT[2],label="期望时刻"); ax.scatter(x,[z[1]/3600 for z in rec],s=14,color=CAT[1],label="预测送达"); ax.set_xlabel("货箱序号"); ax.set_ylabel("时间 (h)"); ax.set_title("逐箱送达时刻与期望时刻",loc="left",fontweight="bold"); ax.legend(frameon=False); style_ax(ax,"y"); savefig(fig,os.path.join(out_dir,f"{tag}_05_逐箱时限.png"))

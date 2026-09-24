# -*- coding: utf-8 -*-
"""Q1-3 Step C：正式组批 + 实体无人机调度（单服务区架次）。

两个方法共用同一调度器与同一物理口径：
* baseline：分服务区 FFD（首批优先/截止早优先）+ 机型取架次最少者；
* formal：分服务区全枚举 + CP-SAT 精确集合划分（最少架次，次优最小闲置）。
调度：按（有首批优先，最早截止优先）排序，同机型最早可用实体机执行；
start = UAV 可用时刻，depart = start + prep + n*box_load，
deliver = depart + fly_out + handover，finish = deliver + fly_back。
输出正式解 canonical 文件；baseline 只存 trips 结构供独立评价器对比。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.data import (  # noqa: E402
    load_boxes,
    load_transport_fleet,
    load_transport_types,
    sid_list,
)
from common.route import leg_energy, leg_time  # noqa: E402

import q1_batch as qb  # noqa: E402

PROJ = Path(__file__).resolve().parents[2]
RES = PROJ / "results"


def build_batches(method: str, seed: int = 7,
                  type_penalty: dict | None = None) -> list[dict]:
    boxes = load_boxes()
    qeff, types = qb.load_qeff()
    trips: list[dict] = []
    for sid in sid_list():
        sub = boxes[boxes["sid"] == sid]
        if method == "baseline":
            g, packs = qb.baseline_choose_type(sub, qeff, types)
            chosen = [(g, p) for p in packs]
        elif method == "formal":
            chosen = qb.exact_cover(sub, qeff, types, seed=seed,
                                    type_penalty=type_penalty)
        else:
            raise ValueError(method)
        for g, pack in chosen:
            trips.append({"sid": sid, "gtype": g, "boxes": list(pack)})
    return trips


def schedule(trips: list[dict], refine: bool = True) -> tuple[list[dict], list[dict], list[dict]]:
    boxes = load_boxes().set_index("box")
    types = load_transport_types()
    fleet = load_transport_fleet()
    uavs = {r.uid: {"gtype": r.gtype, "avail": 0.0, "trips": []}
            for r in fleet.itertuples()}

    def timing(t: dict, start: float) -> tuple[float, float, float]:
        """返回 (depart, deliver, finish)。deliver = 完成交接时刻 = 送达口径。"""
        gt = types[t["gtype"]]
        n = len(t["boxes"])
        prep_load = gt["t_prep"] + n * gt["t_box_load"]
        fly_out = leg_time(t["gtype"], "O01", t["sid"])
        hand = gt["t_hand_base"] + n * gt["t_hand_box"]
        fly_back = leg_time(t["gtype"], t["sid"], "O01")
        depart = start + prep_load
        deliver = depart + fly_out + hand
        return depart, deliver, deliver + fly_back

    # 每架次预计算：箱级（截止，权重，是否首批）
    info = []
    for t in trips:
        bl = [(float(boxes.loc[b, "t_first"]) if bool(boxes.loc[b, "first"])
               else float(boxes.loc[b, "t_exp"]),
               float(boxes.loc[b, "prio"]), bool(boxes.loc[b, "first"]))
              for b in t["boxes"]]
        info.append({"gtype": t["gtype"], "boxes": bl,
                     "has_first": any(x[2] for x in bl),
                     "deadline": min(x[0] for x in bl)})

    def decode(assign: dict) -> tuple[dict, tuple]:
        times: dict[int, tuple] = {}
        for uid in sorted(assign):
            cur = 0.0
            for i in assign[uid]:
                depart, deliver, finish = timing(trips[i], cur)
                times[i] = (cur, depart, deliver, finish)
                cur = finish
        fl_n, fl_max, wtd, cmax = 0, 0.0, 0.0, 0.0
        for i, (_, _, deliver, finish) in times.items():
            cmax = max(cmax, finish)
            for dead, prio, isf in info[i]["boxes"]:
                late = max(0.0, deliver - dead)
                wtd += prio * late
                if isf and late > 1e-9:
                    fl_n += 1
                    fl_max = max(fl_max, late)
        return times, (fl_n, round(fl_max, 6), round(wtd, 6), round(cmax, 6))

    # 初解：分层最小松弛（首批层优先），层内按松弛派单
    unscheduled = set(range(len(trips)))
    prov_avail = {u: 0.0 for u in uavs}
    init_seq: list[tuple[int, str]] = []
    for tier in (True, False):
        while any(info[i]["has_first"] == tier for i in unscheduled):
            best, best_key, best_uid, best_finish = None, None, None, None
            for i in sorted(unscheduled):
                if info[i]["has_first"] != tier:
                    continue
                t = trips[i]
                cand = [u for u, v in uavs.items() if v["gtype"] == t["gtype"]]
                u0 = min(cand, key=lambda u: (prov_avail[u], u))
                _, deliver, finish = timing(t, prov_avail[u0])
                key = (info[i]["deadline"] - deliver, info[i]["deadline"],
                       t["sid"], i)
                if best_key is None or key < best_key:
                    best, best_key, best_uid, best_finish = i, key, u0, finish
            unscheduled.discard(best)
            prov_avail[best_uid] = best_finish
            init_seq.append((best, best_uid))
    assign: dict[str, list[int]] = {u: [] for u in uavs}
    for i, uid in init_seq:
        assign[uid].append(i)

    # 局部搜索：重定位 + 交换，首改进，确定性顺序（探索阶段可关闭以加速）
    _, best_cost = decode(assign)
    if refine:
        for _ in range(60):
            moved = False
            for uid1 in sorted(assign):
                for pos1 in range(len(assign[uid1])):
                    i = assign[uid1][pos1]
                    g = trips[i]["gtype"]
                    for uid2 in sorted(assign):
                        if uavs[uid2]["gtype"] != g:
                            continue
                        for pos2 in range(len(assign[uid2]) + 1):
                            if uid2 == uid1 and pos2 in (pos1, pos1 + 1):
                                continue
                            trial = {u: list(s) for u, s in assign.items()}
                            trial[uid1].pop(pos1)
                            trial[uid2].insert(
                                pos2 - (1 if uid2 == uid1 and pos2 > pos1 else 0), i)
                            _, cost = decode(trial)
                            if cost < best_cost:
                                assign, best_cost = trial, cost
                                moved = True
                                break
                        if moved:
                            break
                    if moved:
                        break
                if moved:
                    break
            if not moved:
                for a in range(len(trips)):
                    if moved:
                        break
                    for b in range(a + 1, len(trips)):
                        ua = next(u for u, s in assign.items() if a in s)
                        ub = next(u for u, s in assign.items() if b in s)
                        if ua != ub and trips[a]["gtype"] != trips[b]["gtype"]:
                            continue
                        trial = {u: list(s) for u, s in assign.items()}
                        pa, pb = trial[ua].index(a), trial[ub].index(b)
                        trial[ua][pa], trial[ub][pb] = trial[ub][pb], trial[ua][pa]
                        _, cost = decode(trial)
                        if cost < best_cost:
                            assign, best_cost = trial, cost
                            moved = True
                            break
            if not moved:
                break
    times, _ = decode(assign)
    _uid_of = {}
    for u, s in assign.items():
        for i in s:
            _uid_of[i] = u
    order = sorted(times, key=lambda i: (times[i][0], _uid_of[i], i))

    trip_rows, box_rows = [], []
    for tid, i in enumerate(order):
        uid = _uid_of[i]
        t = trips[i]
        g, sid, pack = t["gtype"], t["sid"], t["boxes"]
        gt = types[g]
        assert uavs[uid]["gtype"] == g
        start, depart, deliver, finish = times[i]
        n = len(pack)
        fly_out = leg_time(g, "O01", sid)
        payload = float(sum(boxes.loc[b, "mass"] for b in pack))
        volume = float(sum(boxes.loc[b, "vol"] for b in pack))
        e_out = leg_energy(g, "O01", sid, payload)
        e_back = leg_energy(g, sid, "O01", 0.0)
        e_tot = e_out + e_back
        lim_e = (1 - gt["rho"]) * gt["Euse"]
        lim_m = min(float(gt["Q"]), qb.load_qeff()[0][g][sid])
        trip_id = f"T{tid + 1:02d}"
        uavs[uid]["avail"] = finish
        uavs[uid]["trips"].append(trip_id)
        trip_rows.append(dict(
            trip_id=trip_id, uid=uid, gtype=g, sid=sid,
            boxes=";".join(pack), n_boxes=n,
            payload_kg=payload, payload_limit_kg=lim_m,
            payload_utilization=payload / lim_m,
            volume_m3=volume, volume_limit_m3=float(gt["V"]),
            volume_utilization=volume / float(gt["V"]),
            start_time_s=start, departure_time_s=depart,
            arrival_time_s=depart + fly_out, return_time_s=finish,
            finish_time_s=finish, outbound_energy_kwh=e_out,
            return_energy_kwh=e_back, total_energy_kwh=e_tot,
            energy_limit_kwh=lim_e, energy_margin_kwh=lim_e - e_tot,
            binding_constraint=qb.binding_of(payload, volume, lim_m, float(gt["V"]))))
        for b in pack:
            dl = float(boxes.loc[b, "t_first"] if boxes.loc[b, "first"]
                       else boxes.loc[b, "t_exp"])
            late = max(0.0, deliver - dl)
            box_rows.append(dict(
                box=b, sid=sid, type=boxes.loc[b, "type"],
                mass=float(boxes.loc[b, "mass"]), volume=float(boxes.loc[b, "vol"]),
                first=bool(boxes.loc[b, "first"]),
                t_first=None if pd.isna(boxes.loc[b, "t_first"])
                else float(boxes.loc[b, "t_first"]),
                t_exp=float(boxes.loc[b, "t_exp"]),
                prio=float(boxes.loc[b, "prio"]), trip_id=trip_id, uid=uid,
                gtype=g, arrival_time_s=deliver, lateness_s=late,
                weighted_lateness=float(boxes.loc[b, "prio"]) * late,
                first_on_time=(None if not boxes.loc[b, "first"]
                               else bool(deliver <= float(boxes.loc[b, "t_first"]) + 1e-9))))
    uav_rows = []
    for uid, v in uavs.items():
        done = [t for t in trip_rows if t["uid"] == uid]
        busy = sum(t["finish_time_s"] - t["start_time_s"] for t in done)
        last = max([t["finish_time_s"] for t in done], default=0.0)
        first_s = min([t["start_time_s"] for t in done], default=0.0)
        uav_rows.append(dict(
            uid=uid, gtype=v["gtype"], n_trips=len(done),
            first_start_s=first_s, last_finish_s=last,
            busy_time_s=busy, idle_time_s=max(0.0, last - busy),
            total_payload_kg=sum(t["payload_kg"] for t in done),
            total_energy_kwh=sum(t["total_energy_kwh"] for t in done)))
    return trip_rows, box_rows, uav_rows


def _sched_cost(rows: tuple) -> tuple:
    trip_rows, box_rows, _ = rows
    fl = [b for b in box_rows if b["first"] and b["lateness_s"] > 1e-9]
    return (len(fl),
            round(max([b["lateness_s"] for b in fl], default=0.0), 6),
            len(trip_rows),
            round(sum(b["weighted_lateness"] for b in box_rows), 6),
            round(max(t["finish_time_s"] for t in trip_rows), 6))


def _trips_from_covers(covers: dict) -> list[dict]:
    trips: list[dict] = []
    for sid in sid_list():
        for g, pack in covers[sid]:
            trips.append({"sid": sid, "gtype": g, "boxes": list(pack)})
    return trips


def solve_q1(method: str = "formal") -> dict:
    """正式入口（Step C）。method in {baseline, formal}，返回三表 + 耗时。

    formal = 各服务区最少架次精确覆盖池 + 坐标下降联合选择 + 分层 MST/局部
    搜索调度。池内全部覆盖均为最少架次（下降过程保持架次不增）；选择准则
    为调度代价（首批迟到数，最大首批延误，架次数，WTD，Cmax）；全程确定性。
    """
    t0 = time.time()
    if method == "formal":
        boxes = load_boxes()
        qeff, types = qb.load_qeff()
        pools = {sid: qb.cover_pool(boxes[boxes["sid"] == sid], qeff, types,
                                    max_covers=15)
                 for sid in sid_list()}
        cur = {sid: pools[sid][0] for sid in sid_list()}
        best_rows = schedule(_trips_from_covers(cur), refine=False)
        best_cost = _sched_cost(best_rows)
        for _ in range(3):
            improved = False
            for sid in sid_list():
                for cand in pools[sid][1:]:
                    trial = dict(cur)
                    trial[sid] = cand
                    rows = schedule(_trips_from_covers(trial), refine=False)
                    cost = _sched_cost(rows)
                    if cost < best_cost:
                        cur, best_rows, best_cost = trial, rows, cost
                        improved = True
                        break
            if not improved:
                break
        (trip_rows, box_rows, uav_rows) = schedule(_trips_from_covers(cur))
        extra = {"formal_method": "min-trips cover pools + coordinate descent"}
    else:
        trip_rows, box_rows, uav_rows = schedule(build_batches(method))
        extra = {}
    out = {"method": method, "trips": trip_rows, "boxes": box_rows,
           "uavs": uav_rows, "solve_time_s": time.time() - t0}
    out.update(extra)
    return out


def main() -> int:
    RES.mkdir(exist_ok=True)
    times = {}
    for method in ("baseline", "formal"):
        sol = solve_q1(method)
        times[method] = sol["solve_time_s"]
        if "formal_method" in sol:
            times["formal_method"] = sol["formal_method"]
        pd.DataFrame(sol["trips"]).to_csv(RES / f"q1_{method}_trips.csv", index=False)
        print(f"{method}: trips={len(sol['trips'])} "
              f"time={sol['solve_time_s']:.1f}s")
    (RES / "q1_method_times.json").write_text(
        json.dumps(times, ensure_ascii=False, indent=2), encoding="utf-8")
    sol = solve_q1("formal")
    pd.DataFrame(sol["trips"]).to_csv(RES / "q1_solution_trips.csv", index=False)
    pd.DataFrame(sol["boxes"]).to_csv(RES / "q1_solution_boxes.csv", index=False)
    pd.DataFrame(sol["uavs"]).to_csv(RES / "q1_solution_uavs.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

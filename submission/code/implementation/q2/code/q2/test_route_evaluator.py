# -*- coding: utf-8 -*-
"""Q2-B 路线评价器测试：12 类行为断言，预期全部来自 Q1 common 独立计算、
人工公式或真实数据构造，禁止抄写某次运行输出作为断言。

每个测试函数返回审计行 dict；断言失败直接 raise。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "q1" / "code"))

from common.data import load_boxes, load_transport_types  # noqa: E402
from common.route import leg_energy, leg_time  # noqa: E402
from route_evaluator import evaluate_route  # noqa: E402

BTAB = None
TYPES = None


def _data():
    global BTAB, TYPES
    if BTAB is None:
        BTAB = load_boxes().set_index("box")
        TYPES = load_transport_types()
    return BTAB, TYPES


def _row(case_id, gtype, stops, ev, expected, actual, ok=True):
    return {"case_id": case_id, "gtype": gtype, "route": "O01-" + "-".join(stops) + "-O01",
            "n_stops": len(stops), "n_boxes": len(ev.route.box_ids),
            "initial_payload_kg": ev.initial_payload_kg, "initial_volume_m3": ev.initial_volume_m3,
            "leg_payloads": ";".join(f"{l.payload_kg:.3f}" for l in ev.legs),
            "leg_times_s": ";".join(f"{l.time_s:.3f}" for l in ev.legs),
            "leg_energies_kwh": ";".join(f"{l.energy_kwh:.6f}" for l in ev.legs),
            "delivery_offsets_s": ";".join(f"{ev.delivery_offset_by_sid[s]:.3f}" for s in stops),
            "total_energy_kwh": ev.total_route_energy_kwh,
            "energy_limit_kwh": ev.energy_limit_kwh,
            "energy_margin_kwh": ev.energy_margin_kwh,
            "route_duration_s": ev.route_duration_s,
            "mass_feasible": ev.mass_feasible, "volume_feasible": ev.volume_feasible,
            "energy_feasible": ev.energy_feasible, "route_feasible": ev.route_feasible,
            "expected_outcome": expected, "actual_outcome": actual,
            "pass": bool(ok)}


def test_single_stop_regression():
    """6 组单点退化：与 Q1 直接计算逐项一致（普通/较远/能量敏感区全覆盖）。"""
    _, types = _data()
    cases = [("A", "S001", ("S001-MED-01",)), ("A", "S015", ("S015-MED-01",)),
             ("B", "S008", ("S008-MED-01",)), ("B", "S012", ("S012-MED-01",)),
             ("C", "S002", ("S002-MED-01",)), ("C", "S008", ("S008-FOD-01",))]
    rows, tmax, emax = [], 0.0, 0.0
    for g, s, pack in cases:
        ev = evaluate_route(g, [s], {s: pack})
        m = float(BTAB.loc[list(pack), "mass"].sum())
        gt = types[g]
        e1, e2 = leg_energy(g, "O01", s, m), leg_energy(g, s, "O01", 0.0)
        t1, t2 = leg_time(g, "O01", s), leg_time(g, s, "O01")
        assert [l.payload_kg for l in ev.legs] == [m, 0.0]
        assert ev.legs[0].time_s == t1 and ev.legs[1].time_s == t2
        assert ev.legs[0].energy_kwh == e1 and ev.legs[1].energy_kwh == e2
        assert ev.total_route_energy_kwh == e1 + e2
        prep = gt["t_prep"] + len(pack) * gt["t_box_load"]
        hand = gt["t_hand_base"] + len(pack) * gt["t_hand_box"]
        assert abs(ev.route_duration_s - (prep + t1 + hand + t2)) <= 1e-9
        assert ev.energy_limit_kwh == (1 - gt["rho"]) * gt["Euse"]
        assert ev.mass_feasible and ev.volume_feasible and ev.energy_feasible
        tmax = max(tmax, abs(ev.legs[0].time_s - t1), abs(ev.legs[1].time_s - t2))
        emax = max(emax, abs(ev.legs[0].energy_kwh - e1), abs(ev.legs[1].energy_kwh - e2))
        rows.append(_row(f"single-{g}-{s}", g, [s], ev, "match-Q1-direct",
                         "match-Q1-direct"))
    return rows, {"tmax": tmax, "emax": emax}


def test_two_stop_payload_decrease():
    ev = evaluate_route("C", ["S001", "S002"],
                        {"S001": ("S001-MED-01", "S001-FOD-01"),
                         "S002": ("S002-MED-01", "S002-FOD-01")})
    pls = [l.payload_kg for l in ev.legs]
    assert pls == [22.0, 11.0, 0.0], pls
    assert all(b <= a + 1e-9 for a, b in zip(pls, pls[1:]))
    assert pls[-1] == 0.0
    assert ev.route_feasible
    return [_row("two-stop-payload", "C", ["S001", "S002"], ev,
                 "payloads=[22,11,0]", f"payloads={pls}")]


def test_three_stop_payload_decrease():
    ev = evaluate_route("C", ["S002", "S005", "S008"],
                        {"S002": ("S002-MED-01",), "S005": ("S005-MED-01",),
                         "S008": ("S008-MED-01",)})
    pls = [l.payload_kg for l in ev.legs]
    assert pls == [9.0, 6.0, 3.0, 0.0], pls
    assert all(b <= a + 1e-9 for a, b in zip(pls, pls[1:]))
    assert pls[-1] == 0.0
    return [_row("three-stop-payload", "C", ["S002", "S005", "S008"], ev,
                 "payloads=[9,6,3,0]", f"payloads={pls}")]


def test_handover_accumulation():
    """人工公式复核：S2 偏移必须含前站交接（旧 B 版 P0 回归）。"""
    _, types = _data()
    g = "C"
    ev = evaluate_route("C", ["S001", "S002"],
                        {"S001": ("S001-MED-01", "S001-FOD-01"),
                         "S002": ("S002-MED-01", "S002-FOD-01")})
    gt = types[g]
    prep = gt["t_prep"] + 4 * gt["t_box_load"]
    h1 = gt["t_hand_base"] + 2 * gt["t_hand_box"]
    h2 = gt["t_hand_base"] + 2 * gt["t_hand_box"]
    exp1 = prep + leg_time(g, "O01", "S001") + h1
    exp2 = exp1 + leg_time(g, "S001", "S002") + h2
    got1 = ev.delivery_offset_by_sid["S001"]
    got2 = ev.delivery_offset_by_sid["S002"]
    assert abs(got1 - exp1) <= 1e-9, (got1, exp1)
    assert abs(got2 - exp2) <= 1e-9, (got2, exp2)
    return [_row("handover-accumulation", g, ["S001", "S002"], ev,
                 "S2-offset-includes-hand1", "handover-included")]


def test_order_sensitivity():
    """同批货箱不同顺序：载荷轨迹/能耗/时长/偏移应不同（只证差异，不优化）。"""
    boxes_a = {"S001": ("S001-WAT-01",), "S005": ("S005-MED-01",)}
    ev_a = evaluate_route("C", ["S001", "S005"], boxes_a)
    ev_b = evaluate_route("C", ["S005", "S001"],
                          {"S005": ("S005-MED-01",), "S001": ("S001-WAT-01",)})
    pa = [l.payload_kg for l in ev_a.legs]
    pb = [l.payload_kg for l in ev_b.legs]
    assert pa == [17.0, 3.0, 0.0], pa
    assert pb == [17.0, 14.0, 0.0], pb
    assert pa != pb
    assert (ev_a.total_route_energy_kwh, ev_a.route_duration_s,
            tuple(ev_a.delivery_offset_by_sid.values())) != \
           (ev_b.total_route_energy_kwh, ev_b.route_duration_s,
            tuple(ev_b.delivery_offset_by_sid.values()))
    rows = [_row("order-A-S001-S005", "C", ["S001", "S005"], ev_a,
                 "payloads=[17,3,0]", f"E={ev_a.total_route_energy_kwh:.4f}"),
            _row("order-B-S005-S001", "C", ["S005", "S001"], ev_b,
                 "payloads=[17,14,0]", f"E={ev_b.total_route_energy_kwh:.4f}")]
    return rows


def test_mass_infeasible():
    pack = ("S001-WAT-01", "S001-WAT-02", "S001-WAT-03", "S001-WAT-04")
    q0 = float(BTAB.loc[list(pack), "mass"].sum())
    assert q0 > 25.0  # A 额定载荷，构造即超限
    ev = evaluate_route("A", ["S001"], {"S001": pack})
    assert ev.mass_feasible is False and ev.route_feasible is False
    return [_row("mass-infeasible", "A", ["S001"], ev, "mass=False,route=False",
                 "mass-rejected")]


def test_volume_infeasible():
    pack = ("S001-HYG-01", "S001-HYG-02")
    v0 = float(BTAB.loc[list(pack), "vol"].sum())
    m0 = float(BTAB.loc[list(pack), "mass"].sum())
    assert v0 > 0.06 and m0 <= 25.0  # 仅体积超限，隔离判定
    ev = evaluate_route("A", ["S001"], {"S001": pack})
    assert ev.volume_feasible is False and ev.route_feasible is False
    assert ev.mass_feasible is True
    return [_row("volume-infeasible", "A", ["S001"], ev, "volume=False,route=False",
                 "volume-rejected")]


def test_energy_infeasible():
    """C 机 70kg 两站长线：质量体积可行，能量超限（margin<0）。"""
    ev = evaluate_route(
        "C", ["S008", "S012"],
        {"S008": ("S008-MED-01", "S008-WAT-01", "S008-WAT-02", "S008-FOD-01",
                  "S008-HYG-01"),
         "S012": ("S012-MED-01", "S012-WAT-01", "S012-FOD-01")})
    assert ev.mass_feasible is True and ev.volume_feasible is True
    assert ev.energy_feasible is False and ev.route_feasible is False
    assert ev.energy_margin_kwh < 0
    return [_row("energy-infeasible", "C", ["S008", "S012"], ev,
                 "energy=False,margin<0", "energy-rejected")]


def _expect_raise(case_id, gtype, stops, packs, why):
    try:
        evaluate_route(gtype, stops, packs)
    except ValueError:
        return {"case_id": case_id, "gtype": gtype,
                "route": "O01-" + "-".join(stops) + "-O01",
                "n_stops": len(stops), "n_boxes": "",
                "initial_payload_kg": "", "initial_volume_m3": "",
                "leg_payloads": "", "leg_times_s": "", "leg_energies_kwh": "",
                "delivery_offsets_s": "", "total_energy_kwh": "",
                "energy_limit_kwh": "", "energy_margin_kwh": "",
                "route_duration_s": "", "mass_feasible": "",
                "volume_feasible": "", "energy_feasible": "",
                "route_feasible": "",
                "expected_outcome": "ValueError", "actual_outcome": why,
                "pass": True}
    raise AssertionError(f"{case_id} did not raise ValueError")


def test_duplicate_box():
    return [_expect_raise("duplicate-box", "C", ["S001", "S002"],
                          {"S001": ("S001-MED-01",), "S002": ("S001-MED-01",)},
                          "duplicate-rejected")]


def test_sid_mismatch():
    return [_expect_raise("sid-mismatch", "C", ["S002"],
                          {"S002": ("S001-MED-01",)}, "mismatch-rejected")]


def test_unknown_box():
    return [_expect_raise("unknown-box", "C", ["S001"],
                          {"S001": ("BOX-FAKE-001",)}, "unknown-rejected")]


def test_empty_stop():
    return [_expect_raise("empty-stop", "C", ["S001", "S005"],
                          {"S001": ("S001-MED-01",), "S005": ()},
                          "empty-rejected")]

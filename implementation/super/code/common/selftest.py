# -*- coding: utf-8 -*-
"""公共模块自检：打印样例架次的时间/能耗分解，供人工核对量级。"""
from .data import load_nodes, load_transport_types
from .physics import TransportTrip, equiv_range, charge_time, ops_height
from .dem import get_dem

nd = load_nodes()
gts = load_transport_types()
dem = get_dem()

print("=== 等效航程校验 ===")
for g, gt in gts.items():
    print(f"{g}: L(0)={equiv_range(gt,0):.0f} (标称{gt['L0']:.0f}), "
          f"L(Q)={equiv_range(gt,gt['Q']):.0f} (标称{gt['LF']:.0f}), "
          f"L(Q/2)={equiv_range(gt,gt['Q']/2):.0f}")

print("\n=== 单点往返：S001 / S015 逐机型 ===")
for sid in ["S001", "S015"]:
    for g, gt in gts.items():
        tr = TransportTrip(nd, [sid], gt)
        d = tr.energy_detail({sid: 0.0})
        print(f"\n-- {sid} 机型{g}  航距 {tr.legs[0].d:.0f} m, "
              f"巡航海拔 {tr.legs[0].z_cruise:.1f} m (沿途最高 {tr.legs[0].zmax:.1f} m)")
        for r in d:
            print(f"   {r['leg']:>10s} d={r['d']:7.0f} h+={r['h_up']:6.1f} "
                  f"h-={r['h_dn']:6.1f} t={r['t']:7.1f}s "
                  f"E_hor={r['e_hor']:.4f} E_up={r['e_up']:.4f} E={r['e']:.4f} kWh")
        # 空载总能耗
        E0 = tr.total_energy({sid: 0.0})
        lim = (1 - gt["rho"]) * gt["Euse"]
        print(f"   空载总能耗 {E0:.4f} kWh / 限值 {lim:.4f} kWh  "
              f"(剩余 {lim-E0:.4f})")
        print(f"   最大安全载荷(能量口径) {tr.max_payload():.2f} kg "
              f"vs 机型上限 {gt['Q']:.0f} kg")
        print(f"   单站架次总时长 {tr.total_time({sid:0.0}, {sid:['x']}):.1f} s")

print("\n=== 充电模型校验 (T_full=1800 s) ===")
for s in [0.0, 0.2, 0.5, 0.8, 0.9, 0.95, 1.0]:
    print(f"  SOC={s:.2f} -> t_chg={charge_time(1800, s):7.1f} s")

# -*- coding: utf-8 -*-
"""场景数据装载：调度中心、服务区、货箱、运输/中继无人机、能源组件、通信参数。

原始 Excel 为"表头分块"式排版，这里统一解析为规整的 DataFrame / dict，
后续所有求解脚本只通过本模块取数，避免口径不一致。
"""
from __future__ import annotations

import functools
import pandas as pd

from .config import BASE_DATA


def _num(x):
    """把可能带空格的数值/缺失值统一成 float 或 None。"""
    if x is None:
        return None
    if isinstance(x, str):
        x = x.strip()
        if x == "" :
            return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


# ------------------------------------------------------------------ 节点
@functools.lru_cache(maxsize=1)
def load_nodes() -> pd.DataFrame:
    """返回 O01 + S001..S015 的节点表。

    列：id, kind('O'/'S'), name, lon, lat, elev, pop
    """
    df = pd.read_excel(BASE_DATA / "调度中心与服务区.xlsx", sheet_name="数据", header=None)
    o = df.iloc[2]
    rows = [dict(id="O01", kind="O", name=str(o[1]).strip(),
                 lon=_num(o[2]), lat=_num(o[3]), elev=_num(o[4]), pop=0)]
    for i in range(6, 21):
        r = df.iloc[i]
        if pd.isna(r[0]):
            continue
        rows.append(dict(id=str(r[0]).strip(), kind="S", name=str(r[1]).strip(),
                         lon=_num(r[2]), lat=_num(r[3]), elev=_num(r[4]),
                         pop=int(_num(r[5]) or 0)))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ 货箱
@functools.lru_cache(maxsize=1)
def load_boxes() -> pd.DataFrame:
    """逐箱货箱清单（80 箱）。列：box, sid, type, mass, vol, first, t_first, t_exp, prio"""
    df = pd.read_excel(BASE_DATA / "物资需求与配送时限.xlsx", sheet_name="逐箱货箱清单", header=0)
    df.columns = [str(c).strip() for c in df.columns]
    out = pd.DataFrame({
        "box":   df["货箱编号"].astype(str).str.strip(),
        "sid":   df["服务区编号"].astype(str).str.strip(),
        "type":  df["物资类型"].astype(str).str.strip(),
        "mass":  df["单箱质量（kg）"].map(_num),
        "vol":   df["单箱体积（m³）"].map(_num),
        "first": df["是否首批保障"].astype(str).str.strip().eq("是"),
        "t_first": df["首批截止时间（s）"].map(_num),
        "t_exp":   df["期望送达时间（s）"].map(_num),
        "prio":    df["应急优先系数"].map(_num),
    })
    return out.reset_index(drop=True)


@functools.lru_cache(maxsize=1)
def load_demand() -> pd.DataFrame:
    """服务区-物资类型级需求汇总（用于统计与校验）。"""
    df = pd.read_excel(BASE_DATA / "物资需求与配送时限.xlsx", sheet_name="数据", header=0)
    df.columns = [str(c).strip() for c in df.columns]
    return df


# ------------------------------------------------------------------ 运输无人机
@functools.lru_cache(maxsize=1)
def load_transport_types() -> dict:
    """三种运输机型参数字典。键为 'A'/'B'/'C'。

    统一字段名：m_empty, Q(最大载货kg), V(可用装载体积m^3), vc(巡航m/s),
    L0(空载标准航程m), LF(满载标准航程m), Euse(电池可用能量kWh),
    rho(返航安全余量比例), t_prep(工位固定准备s), t_box_load(每箱装载s),
    t_hand_base(接收点基础交接s), t_hand_box(每箱增加交接s),
    v_up, v_down, eta_up, eta_down
    """
    df = pd.read_excel(BASE_DATA / "运输无人机数据.xlsx", sheet_name="数据", header=None)
    res = {}
    for i in range(2, 5):
        r = df.iloc[i]
        res[str(r[0]).strip()] = dict(
            code=str(r[0]).strip(), name=str(r[1]).strip(),
            m_empty=_num(r[2]), Q=_num(r[3]), V=_num(r[4]),
            vc=_num(r[5]), L0=_num(r[6]), LF=_num(r[7]),
            Euse=_num(r[8]), rho=_num(r[9]) / 100.0,
            t_prep=_num(r[10]), t_box_load=_num(r[11]),
            t_hand_base=_num(r[12]), t_hand_box=_num(r[13]),
            v_up=_num(r[14]), v_down=_num(r[15]),
            eta_up=_num(r[16]), eta_down=_num(r[17]),
        )
    return res


@functools.lru_cache(maxsize=1)
def load_transport_fleet() -> pd.DataFrame:
    """8 架实体运输无人机：U01..U08 -> 机型。"""
    df = pd.read_excel(BASE_DATA / "运输无人机数据.xlsx", sheet_name="数据", header=None)
    rows = []
    for i in range(8, 16):
        r = df.iloc[i]
        if pd.isna(r[0]):
            continue
        rows.append(dict(uid=str(r[0]).strip(), gtype=str(r[1]).strip(),
                         home=str(r[2]).strip()))
    return pd.DataFrame(rows)


@functools.lru_cache(maxsize=1)
def load_transport_batteries() -> dict:
    """各机型共享电池：总数与等效完全充电时间(s)。"""
    df = pd.read_excel(BASE_DATA / "运输无人机数据.xlsx", sheet_name="数据", header=None)
    return {str(df.iloc[i][0]).strip(): dict(n=int(_num(df.iloc[i][1])),
                                             t_full=_num(df.iloc[i][2]))
            for i in range(19, 22)}


# ------------------------------------------------------------------ 中继无人机
@functools.lru_cache(maxsize=1)
def load_relay_type() -> dict:
    df = pd.read_excel(BASE_DATA / "中继无人机数据.xlsx", sheet_name="数据", header=None)
    r = df.iloc[2]
    return dict(code=str(r[0]).strip(), name=str(r[1]).strip(),
                m_empty=_num(r[2]), m_comm=_num(r[3]), m_takeoff=_num(r[4]),
                vc=_num(r[5]), p_cruise=_num(r[6]), Euse=_num(r[7]),
                rho=_num(r[8]) / 100.0, t_prep=_num(r[9]), t_link=_num(r[10]),
                t_turn=_num(r[11]), v_up=_num(r[12]), v_down=_num(r[13]),
                eta_up=_num(r[14]), eta_down=_num(r[15]),
                p_hover=_num(r[16]), p_comm=_num(r[17]),
                max_hover_agl=_num(r[18]))


@functools.lru_cache(maxsize=1)
def load_relay_fleet() -> pd.DataFrame:
    df = pd.read_excel(BASE_DATA / "中继无人机数据.xlsx", sheet_name="数据", header=None)
    rows = []
    for i in range(6, 8):
        r = df.iloc[i]
        if pd.isna(r[0]):
            continue
        rows.append(dict(rid=str(r[0]).strip(), rtype=str(r[1]).strip(),
                         home=str(r[2]).strip()))
    return pd.DataFrame(rows)


@functools.lru_cache(maxsize=1)
def load_relay_energy_modules() -> dict:
    df = pd.read_excel(BASE_DATA / "中继无人机数据.xlsx", sheet_name="数据", header=None)
    r = df.iloc[11]
    return dict(n=int(_num(r[1])), t_full=_num(r[2]))


# ------------------------------------------------------------------ 通信参数
@functools.lru_cache(maxsize=1)
def load_comm_params() -> dict:
    from .config import CARRIER_MHZ, L_SYS, L_OBS, P_SENS, FADE_MARGIN
    return dict(f=CARRIER_MHZ, Lsys=L_SYS, Lobs=L_OBS,
                Psens=P_SENS, M=FADE_MARGIN, Pth=P_SENS + FADE_MARGIN)


def sid_list() -> list:
    return [f"S{i:03d}" for i in range(1, 16)]


def node_elev_map() -> dict:
    n = load_nodes()
    return dict(zip(n["id"], n["elev"]))


def node_coord_map() -> dict:
    n = load_nodes()
    return {r.id: (r.lon, r.lat) for r in n.itertuples()}


if __name__ == "__main__":
    n = load_nodes()
    b = load_boxes()
    print("节点：", len(n), list(n["id"]))
    print("货箱：", len(b), "总质量 %.1f kg  总体积 %.4f m^3" % (b["mass"].sum(), b["vol"].sum()))
    print("首批箱：", int(b["first"].sum()))
    print("运输机型：", {k: (v["Q"], v["V"], v["Euse"]) for k, v in load_transport_types().items()})
    print("机队：\n", load_transport_fleet().to_string())
    print("电池：", load_transport_batteries())
    print("中继：", load_relay_type())
    print("中继能源组件：", load_relay_energy_modules())

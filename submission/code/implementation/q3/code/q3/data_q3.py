"""Q3 data accessors.

All relay and communication values are read from the official Excel
attachments at runtime.  The Q1 common data layer remains the source of the
transport fleet, nodes, DEM and transport physics; this module does not copy
those numerical constants.
"""
from __future__ import annotations

import functools
import sys
from pathlib import Path
from typing import Any

import pandas as pd

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[4]
Q1_CODE = REPO_ROOT / "implementation" / "q1" / "code"
if str(Q1_CODE) not in sys.path:
    sys.path.insert(0, str(Q1_CODE))

from common.data import (  # noqa: E402
    load_nodes,
    load_transport_batteries,
    load_transport_fleet,
    load_transport_types,
)
from common.config import DEM_TIF  # noqa: E402

BASE_DATA = REPO_ROOT / "data" / "raw" / "tabular" / "无人机应急物资运输基础数据"
RELAY_XLSX = BASE_DATA / "中继无人机数据.xlsx"
COMM_XLSX = BASE_DATA / "通信链路参数.xlsx"
NODES_XLSX = BASE_DATA / "调度中心与服务区.xlsx"


def _num(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _required(value: Any, label: str) -> float:
    out = _num(value)
    if out is None:
        raise ValueError(f"missing numeric Q3 input: {label}")
    return out


@functools.lru_cache(maxsize=1)
def load_relay_type_q3() -> dict[str, Any]:
    df = pd.read_excel(RELAY_XLSX, sheet_name="数据", header=None)
    row = df.iloc[2]
    return {
        "code": str(row.iloc[0]).strip(),
        "name": str(row.iloc[1]).strip(),
        "m_empty_kg": _required(row.iloc[2], "relay m_empty_kg"),
        "m_comm_kg": _required(row.iloc[3], "relay m_comm_kg"),
        "m_takeoff_kg": _required(row.iloc[4], "relay m_takeoff_kg"),
        "cruise_speed_mps": _required(row.iloc[5], "relay cruise_speed_mps"),
        "cruise_power_kw": _required(row.iloc[6], "relay cruise_power_kw"),
        "Euse_kwh": _required(row.iloc[7], "relay Euse_kwh"),
        "reserve_rho": _required(row.iloc[8], "relay reserve_rho_pct") / 100.0,
        "prep_time_s": _required(row.iloc[9], "relay prep_time_s"),
        "link_setup_s": _required(row.iloc[10], "relay link_setup_s"),
        "turnaround_s": _required(row.iloc[11], "relay turnaround_s"),
        "climb_speed_mps": _required(row.iloc[12], "relay climb_speed_mps"),
        "descent_speed_mps": _required(row.iloc[13], "relay descent_speed_mps"),
        "climb_efficiency": _required(row.iloc[14], "relay climb_efficiency"),
        "descent_efficiency": _required(row.iloc[15], "relay descent_efficiency"),
        "hover_power_kw": _required(row.iloc[16], "relay hover_power_kw"),
        "communication_power_kw": _required(row.iloc[17], "relay communication_power_kw"),
        "max_hover_agl_m": _required(row.iloc[18], "relay max_hover_agl_m"),
        "source": str(RELAY_XLSX),
    }


@functools.lru_cache(maxsize=1)
def load_relay_fleet_q3() -> list[dict[str, Any]]:
    df = pd.read_excel(RELAY_XLSX, sheet_name="数据", header=None)
    rows = []
    for idx in range(6, 8):
        row = df.iloc[idx]
        if pd.isna(row.iloc[0]):
            continue
        rows.append({"rid": str(row.iloc[0]).strip(),
                     "rtype": str(row.iloc[1]).strip(),
                     "home": str(row.iloc[2]).strip()})
    return rows


@functools.lru_cache(maxsize=1)
def load_relay_energy_q3() -> dict[str, Any]:
    df = pd.read_excel(RELAY_XLSX, sheet_name="数据", header=None)
    row = df.iloc[11]
    return {"rtype": str(row.iloc[0]).strip(),
            "count": int(_required(row.iloc[1], "relay energy component count")),
            "t_full_s": _required(row.iloc[2], "relay energy component t_full_s"),
            "source": str(RELAY_XLSX)}


@functools.lru_cache(maxsize=1)
def load_comm_q3() -> dict[str, Any]:
    """Read link-budget rows without relying on Q1's communication constants."""
    df = pd.read_excel(COMM_XLSX, sheet_name="数据", header=None)
    scalars: dict[str, float] = {}
    pt_rows: list[float] = []
    gain_rows: list[float] = []
    subject_rows: list[str] = []
    for _, row in df.iloc[2:].iterrows():
        key = str(row.iloc[3]).strip() if not pd.isna(row.iloc[3]) else ""
        value = _num(row.iloc[4])
        subject = str(row.iloc[0]).strip() if not pd.isna(row.iloc[0]) else ""
        if value is None:
            continue
        if key in {"f", "Lsys", "Lobs", "Psens", "M", "hG"}:
            scalars[key] = value
        elif key == "Pt":
            pt_rows.append(value)
            subject_rows.append(subject)
        elif key == "G":
            gain_rows.append(value)
    if len(pt_rows) != 4 or len(gain_rows) != 4:
        raise ValueError("communication workbook must contain four Pt and four G rows")
    interfaces = {
        "U": {"Pt_dBm": pt_rows[0], "Gt_dBi": gain_rows[0]},
        "RA": {"Pt_dBm": pt_rows[1], "Gt_dBi": gain_rows[1]},
        "RB": {"Pt_dBm": pt_rows[2], "Gt_dBi": gain_rows[2]},
        "G01": {"Pt_dBm": pt_rows[3], "Gt_dBi": gain_rows[3]},
    }
    required = {"f", "Lsys", "Lobs", "Psens", "M", "hG"}
    missing = required - set(scalars)
    if missing:
        raise ValueError(f"communication workbook missing keys: {sorted(missing)}")
    return {
        "frequency_mhz": scalars["f"],
        "system_loss_db": scalars["Lsys"],
        "obstruction_loss_db": scalars["Lobs"],
        "receiver_sensitivity_dbm": scalars["Psens"],
        "fade_margin_db": scalars["M"],
        "gateway_antenna_height_m": scalars["hG"],
        "threshold_dbm": scalars["Psens"] + scalars["M"],
        "interfaces": interfaces,
        "source": str(COMM_XLSX),
        "raw_pt_subjects": subject_rows,
    }


@functools.lru_cache(maxsize=1)
def load_q3_inputs() -> dict[str, Any]:
    relay_type = dict(load_relay_type_q3())
    relay_energy = load_relay_energy_q3()
    relay_type["energy_t_full_s"] = float(relay_energy["t_full_s"])
    return {
        "relay_type": relay_type,
        "relay_fleet": load_relay_fleet_q3(),
        "relay_energy": relay_energy,
        "communication": load_comm_q3(),
        "nodes": load_nodes().copy(),
        "transport_types": load_transport_types(),
        "transport_fleet": load_transport_fleet().copy(),
        "transport_batteries": load_transport_batteries(),
        "dem_path": str(DEM_TIF),
        "sources": {"relay": str(RELAY_XLSX), "communication": str(COMM_XLSX),
                    "nodes": str(NODES_XLSX), "dem": str(DEM_TIF)},
    }


def data_audit() -> dict[str, Any]:
    inputs = load_q3_inputs()
    rt = inputs["relay_type"]
    comm = inputs["communication"]
    return {
        "status": "PASS",
        "sources": inputs["sources"],
        "relay": {"type": rt, "fleet": inputs["relay_fleet"],
                   "count": len(inputs["relay_fleet"]),
                   "energy_components": inputs["relay_energy"]},
        "communication": comm,
        "transport_interface": {k: {"vc_mps": float(v["vc"]),
                                     "Euse_kwh": float(v["Euse"]),
                                     "rho": float(v["rho"])}
                                 for k, v in inputs["transport_types"].items()},
        "nodes": {"count": int(len(inputs["nodes"])),
                  "ids": [str(x) for x in inputs["nodes"]["id"]]},
    }

# -*- coding: utf-8 -*-
"""Phase Q1-3 预开发骨架：模型接口、约束结构与验证占位。

定位（冻结声明）：
* 本模块只定义 Q1-3 正式求解未来需要的数据结构与纯约束函数；
* 不执行正式货箱组批、不做机型选择、不做路线优化、不调用任何求解器；
* 不假设、不估计、不硬编码、不重新计算正式 q_max；
* 正式 q_max 唯一来源是 ``results/q1_capacity.csv``，且仅当 Q1-2 通过验收后可用。

质量与体积是两个独立约束，禁止把体积折算成质量。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional

import pandas as pd

# ---------------------------------------------------------------- 阶段门
# Q1-2 尚未最终验收。本骨架阶段该门恒为 False，任何正式求解入口都必须
# 通过它拒绝运行；只有在 Q1-2 被明确宣布 PASS 后才允许翻转。
Q1_2_APPROVED = False

# q1_capacity.csv 的结构契约（列名来自 Q1-2 输出，不含任何数值结果）。
CAPACITY_REQUIRED_COLUMNS = {
    "sid",
    "gtype",
    "rated_payload_kg",
    "q_max_kg",
    "q_max_ratio",
    "capacity_status",
    "qmax_feasible",
}
CAPACITY_LEGAL_STATUS = {"RATED_CAPACITY", "ENERGY_LIMITED", "EMPTY_TRIP_INFEASIBLE"}
CAPACITY_STATUS_WAITING = "WAITING_Q1_2"
CAPACITY_STATUS_AVAILABLE_UNAPPROVED = "Q1_2_RESULT_AVAILABLE_BUT_NOT_YET_APPROVED"

# 单服务区候选批次枚举的安全上限：骨架阶段只允许小规模接口测试，
# 拒绝任何接近真实全量规模的枚举，防止变相提前求解。
CANDIDATE_ENUM_MAX_BOXES = 12


def capacity_table_path() -> Path:
    """未来正式 q1_capacity.csv 的标准位置（Q1-2 输出）。"""
    return Path(__file__).resolve().parents[2] / "results" / "q1_capacity.csv"


# ---------------------------------------------------------------- 数据结构
@dataclass(frozen=True)
class BoxItem:
    box_id: str
    sid: str
    mass: float
    volume: float
    is_first: bool
    first_deadline_s: float | None = None
    expected_time_s: float | None = None
    priority: float = 0.0


@dataclass(frozen=True)
class TripCandidate:
    gtype: str
    stops: tuple[str, ...]
    boxes: tuple[str, ...]
    total_mass: float
    total_volume: float
    meta: Mapping[str, object] = field(default_factory=dict)


def boxes_from_dataframe(df: pd.DataFrame) -> list[BoxItem]:
    """把 load_boxes() 的 DataFrame 转为 BoxItem 列表（字段直转，无推导）。"""
    items: list[BoxItem] = []
    for r in df.itertuples():
        t_first = None if pd.isna(r.t_first) else float(r.t_first)
        t_exp = None if pd.isna(r.t_exp) else float(r.t_exp)
        items.append(BoxItem(
            box_id=str(r.box), sid=str(r.sid),
            mass=float(r.mass), volume=float(r.vol),
            is_first=bool(r.first),
            first_deadline_s=t_first, expected_time_s=t_exp,
            priority=0.0 if pd.isna(r.prio) else float(r.prio),
        ))
    return items


# ---------------------------------------------------------------- q_max 接入
def load_q1_capacity(
    path: Optional[Path | str] = None,
) -> tuple[str, Optional[pd.DataFrame]]:
    """读取 Q1-2 输出表；不存在则返回 WAITING 状态并停止正式求解。

    返回 (status, df)：文件缺失时 df 为 None。即使文件存在，本骨架阶段
    也不将其视为已验收可用（见 Q1_2_APPROVED 门）。
    """
    p = Path(path) if path is not None else capacity_table_path()
    if not p.is_file():
        return CAPACITY_STATUS_WAITING, None
    df = pd.read_csv(p)
    if not Q1_2_APPROVED:
        return CAPACITY_STATUS_AVAILABLE_UNAPPROVED, df
    return "Q1_2_APPROVED", df


def validate_capacity_table(df: pd.DataFrame) -> dict:
    """结构校验：只检查形状、列、值域与状态合法性，不判定数值最优性。

    注意：此处不许断言 39/6 等结果计数；计数只用于报告，不用于放行。
    正式放行还要求 Q1_2_APPROVED 门为 True，由调用方另行检查。
    """
    checks: dict[str, bool] = {}
    checks["has_required_columns"] = CAPACITY_REQUIRED_COLUMNS.issubset(set(df.columns))
    checks["n_rows_is_45"] = len(df) == 45
    if {"sid", "gtype"}.issubset(df.columns):
        checks["n_sids_is_15"] = df["sid"].nunique() == 15
        checks["each_sid_has_3_gtypes"] = bool(
            (df.groupby("sid")["gtype"].nunique() == 3).all()
        )
        checks["gtypes_are_ABC"] = set(df["gtype"].unique().tolist()) <= {"A", "B", "C"}
    else:
        checks["n_sids_is_15"] = False
        checks["each_sid_has_3_gtypes"] = False
        checks["gtypes_are_ABC"] = False
    if {"q_max_kg", "rated_payload_kg", "q_max_ratio"}.issubset(df.columns):
        checks["qmax_positive"] = bool((df["q_max_kg"] > 0).all())
        checks["qmax_within_rated"] = bool(
            (df["q_max_kg"] <= df["rated_payload_kg"] + 1e-9).all()
        )
        checks["qmax_ratio_in_range"] = bool(
            ((df["q_max_ratio"] > 0) & (df["q_max_ratio"] <= 1 + 1e-9)).all()
        )
    else:
        checks["qmax_positive"] = False
        checks["qmax_within_rated"] = False
        checks["qmax_ratio_in_range"] = False
    if {"capacity_status", "qmax_feasible"}.issubset(df.columns):
        checks["status_legal"] = bool(
            df["capacity_status"].isin(CAPACITY_LEGAL_STATUS).all()
        )
        checks["qmax_feasible_all"] = bool(df["qmax_feasible"].fillna(False).all())
    else:
        checks["status_legal"] = False
        checks["qmax_feasible_all"] = False
    checks["all_structural_pass"] = bool(all(checks.values()))
    return checks


def resolve_qmax(
    gtype: str, sid: str, cap_df: Optional[pd.DataFrame], approved: bool = False
) -> Optional[float]:
    """从已验收容量表解析 q_max(g, s)；未验收时一律返回 None。

    骨架阶段 approved 恒为 False，因此本函数当前恒返回 None。
    保留该签名是为了让未来正式代码在同一入口自动继承 Q1-2 更新。
    """
    if not approved or cap_df is None:
        return None
    sub = cap_df[(cap_df["gtype"] == gtype) & (cap_df["sid"] == sid)]
    if len(sub) != 1:
        return None
    return float(sub.iloc[0]["q_max_kg"])


# ---------------------------------------------------------------- 纯约束函数
def check_single_service_mass_capacity(total_mass: float, qmax_kg: float) -> bool:
    """单服务区任务质量约束：sum(m) <= q_max(g, s)。"""
    return bool(total_mass <= qmax_kg + 1e-9)


def check_volume_capacity(total_volume: float, Vg: float) -> bool:
    """体积约束：sum(v) <= V_g（独立约束，不折算为质量）。"""
    return bool(total_volume <= Vg + 1e-12)


def check_rated_mass(total_mass: float, Qg: float) -> bool:
    """额定载荷防御性检查：sum(m) <= Q_g。"""
    return bool(total_mass <= Qg + 1e-9)


def check_box_assignment_unique(
    assignment: Mapping[str, str] | Iterable[tuple[str, str]],
) -> tuple[bool, list[str]]:
    """单箱不可拆分/唯一分配：同一 box 不得同时归属两个架次。

    接受 ``box_id -> trip_id`` 映射，或 ``(box_id, trip_id)`` 对列表；
    后者可表达“同一箱被分配两次”的非法情形并被检出。
    """
    if isinstance(assignment, Mapping):
        pairs = list(assignment.items())
    else:
        pairs = list(assignment)
    box_ids = [b for b, _ in pairs]
    dupes = sorted({b for b in box_ids if box_ids.count(b) > 1})
    return (len(dupes) == 0, dupes)


def check_all_boxes_assigned(
    all_box_ids: Iterable[str],
    assignment: Mapping[str, str] | Iterable[tuple[str, str]],
) -> tuple[bool, list[str]]:
    """全覆盖检查：每个货箱恰好被分配一次；返回 (是否通过, 缺失或重复的箱)。"""
    all_ids = list(all_box_ids)
    assigned = list(assignment.keys()) if isinstance(assignment, Mapping) else [b for b, _ in assignment]
    missing = sorted(set(all_ids) - set(assigned))
    extra = sorted(set(assigned) - set(all_ids))
    problems = missing + extra
    return (len(problems) == 0, problems)


def first_batch_boxes(df: pd.DataFrame) -> pd.DataFrame:
    """取出首批保障货箱子集（只做筛选，不计算到达时间）。"""
    return df[df["first"]].copy().reset_index(drop=True)


def check_first_batch_fields(df: pd.DataFrame) -> dict:
    """首批字段完整性：数量、归属服务区、截止时间是否齐全。"""
    first = first_batch_boxes(df)
    has_deadline = first["t_first"].notna() if len(first) else pd.Series([], dtype=bool)
    return {
        "n_first_boxes": int(len(first)),
        "first_sids": sorted(first["sid"].unique().tolist()) if len(first) else [],
        "first_mass_kg": float(first["mass"].sum()) if len(first) else 0.0,
        "first_volume_m3": float(first["vol"].sum()) if len(first) else 0.0,
        "all_first_have_deadline": bool(has_deadline.all()) if len(first) else True,
    }


def check_box_has_feasible_type(
    mass: float,
    volume: float,
    sid: str,
    types: Mapping[str, Mapping[str, float]],
    cap_df: Optional[pd.DataFrame] = None,
    approved: bool = False,
) -> Optional[bool]:
    """单箱可行机型存在性：是否存在某机型同时满足质量与体积。

    无已验收容量表时返回 None（未知），不做猜测；未来有表后返回 True/False。
    """
    if not approved or cap_df is None:
        return None
    for gtype, t in types.items():
        qmax = resolve_qmax(gtype, sid, cap_df, approved=True)
        if qmax is None:
            continue
        if mass <= qmax + 1e-9 and volume <= float(t["V"]) + 1e-12:
            return True
    return False


# ---------------------------------------------------------------- 候选批次接口
def generate_single_service_candidate_batches(
    boxes: list[BoxItem],
    gtype: str,
    qmax_kg: float,
    Vg: float,
    max_boxes: int = CANDIDATE_ENUM_MAX_BOXES,
) -> list[TripCandidate]:
    """单服务区候选批次生成器（骨架接口，仅小规模测试）。

    枚举满足质量与体积约束的非空子集；输入规模超过 max_boxes 时直接
    拒绝，避免变相全量求解。正式全量生成策略待 Q1-2 验收后另行确定，
    此处不预设 bin packing/knapsack/MILP/贪心中的任何一种。
    """
    if len(boxes) > max_boxes:
        raise ValueError(
            f"candidate enumeration refused: n_boxes={len(boxes)} exceeds "
            f"skeleton limit {max_boxes}"
        )
    sids = {b.sid for b in boxes}
    if len(sids) > 1:
        raise ValueError("single-service generator got multi-service boxes")
    sid = next(iter(sids)) if sids else ""
    out: list[TripCandidate] = []
    n = len(boxes)
    for mask in range(1, 1 << n):
        sel = [boxes[i] for i in range(n) if mask & (1 << i)]
        m = sum(b.mass for b in sel)
        v = sum(b.volume for b in sel)
        if m <= qmax_kg + 1e-9 and v <= Vg + 1e-12:
            out.append(TripCandidate(
                gtype=gtype, stops=(sid,),
                boxes=tuple(b.box_id for b in sel),
                total_mass=m, total_volume=v,
            ))
    return out


# ---------------------------------------------------------------- 正式入口（锁定）
def solve_q1(*args, **kwargs):
    """Q1-3 正式求解统一入口（当前锁定，禁止调用求解器）。"""
    raise RuntimeError(
        "Q1-3 formal solve is locked until Q1-2 capacity results are validated."
    )

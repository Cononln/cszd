"""Q2 统一硬截止口径。

当前正式 Q1 数据字段为 ``first``、``t_first``、``type`` 和 ``t_exp``。首批
保障箱与医疗物资都属于硬截止；若一箱同时满足两种条件，取两者中更早的
时刻。其他物资的 ``t_exp`` 只用于后续软及时性目标，不自动变成硬约束。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

MEDICAL_TYPE = "医疗物资"


def _finite(row: Mapping[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"deadline field {key!r} is not numeric: {value!r}") from exc
    return value if pd.notna(value) else None


def is_medical(row: Mapping[str, Any]) -> bool:
    return str(row.get("type", "")).strip() == MEDICAL_TYPE


def hard_deadline(row: Mapping[str, Any]) -> float | None:
    """Return the strictest hard deadline for one canonical box row."""
    candidates: list[float] = []
    if bool(row.get("first", False)):
        value = _finite(row, "t_first")
        if value is None:
            raise ValueError(f"first box {row.get('box', '<unknown>')} has no t_first")
        candidates.append(value)
    if is_medical(row):
        value = _finite(row, "t_exp")
        if value is None:
            raise ValueError(f"medical box {row.get('box', '<unknown>')} has no t_exp")
        candidates.append(value)
    return min(candidates) if candidates else None


def deadline_kind(row: Mapping[str, Any]) -> str:
    """Explain which hard rule applies, for audit and output metadata."""
    first = bool(row.get("first", False))
    medical = is_medical(row)
    if first and medical:
        return "first_and_medical_min"
    if first:
        return "first"
    if medical:
        return "medical"
    return "none"


def add_deadline_columns(boxes: pd.DataFrame) -> pd.DataFrame:
    """Return a copy annotated with Q2 hard-deadline columns."""
    out = boxes.copy()
    out["hard_deadline_s"] = [hard_deadline(row) for row in out.to_dict("records")]
    out["hard_deadline_kind"] = [deadline_kind(row) for row in out.to_dict("records")]
    return out

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Q1 frozen-result plotting entry point.

This module is deliberately downstream of the Q1 solver.  It reads only the
committed result tables under ``implementation/q1/results`` and writes figures
and QA artifacts under ``implementation/q1/figures``.  It never imports a
solver, changes a result table, or reruns an optimization model.

Run from the repository root (or from any working directory):

    python implementation/q1/code/q1/plot_q1_results.py

The output is a small, reproducible Nature-style figure bundle: PDF, 600-dpi
PNG, editable-text SVG, panel-alignment records, collision audits, a figure
manifest, and a plot report.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, LogLocator, MaxNLocator, PercentFormatter
import numpy as np
import pandas as pd

# Mandatory Nature-figure editable-text settings.  Noto Sans SC supplies the
# Chinese glyphs while Arial remains the first Latin/number choice.
plt.rcParams['font.family'] = 'sans-serif'
# Noto Sans SC is available in the selected runtime and prevents Chinese
# labels from being silently dropped; it contains the same readable Latin
# glyphs needed by the axes.  Arial remains in the fallback family.
plt.rcParams['font.sans-serif'] = ['Noto Sans SC', 'Arial', 'DejaVu Sans', 'Liberation Sans']
plt.rcParams['svg.fonttype'] = 'none'
plt.rcParams['pdf.fonttype'] = 42
plt.rcParams['ps.fonttype'] = 42
plt.rcParams['axes.unicode_minus'] = False
# Keep the literal update form machine-auditable by the Nature source
# preflight and make the editable-text contract explicit.
mpl.rcParams.update({'svg.fonttype': 'none', 'pdf.fonttype': 42})
plt.rcParams["figure.dpi"] = 160
plt.rcParams["savefig.facecolor"] = "white"


# ---------------------------------------------------------------------------
# Paths, palette, and small data structures
# ---------------------------------------------------------------------------

Q1_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Q1_ROOT.parents[1]
RESULTS = Q1_ROOT / "results"
FIGURES = Q1_ROOT / "figures"

REQUIRED_FILES = {
    "final": "q1_final.json",
    "capacity": "q1_capacity.csv",
    "physics": "q1_physics_audit.csv",
    "energy_checks": "q1_physics_energy_checks.csv",
    "trips": "q1_solution_trips.csv",
    "boxes": "q1_solution_boxes.csv",
    "service": "q1_service_summary.csv",
    "comparison": "q1_method_comparison.csv",
    "lexicographic": "q1_lexicographic_stages.csv",
    "solver": "q1_solver_status.csv",
}

# The mapping is intentionally fixed once and reused across all figures.  It
# follows the legacy Q1 figures: A blue, B orange, C green.
COLORS = {
    "A": "#4C72B0",
    "B": "#DD8452",
    "C": "#55A868",
    "baseline": "#8F8F8F",
    "formal": "#4C72B0",
    "accent": "#B64342",
    "pass": "#2A9D8F",
    "neutral": "#D8D8D8",
    "ink": "#272727",
    "grid": "#E5E7EB",
}

STAGE_COLORS = {"L1": "#4C72B0", "L2": "#DD8452", "L3": "#55A868"}
METHOD_COLORS = {"baseline": COLORS["baseline"], "formal": COLORS["formal"]}

CAPACITY_CMAP = LinearSegmentedColormap.from_list(
    "q1_capacity_ratio", ["#F3F5F7", "#B9D8E8", "#3775BA"], N=256
)

EXPECTED = {
    # These are sanity checks against the frozen Q1 report, not optimization
    # constraints.  The source CSV/JSON remains authoritative for plotting.
    "assigned_boxes": 80,
    "n_trips": 18,
    "n_services": 15,
    "solver_stages": 45,
    "formal_energy_kwh": 59.08291742366984,
    "formal_operation_time_s": 32804.128230148934,
    "baseline_energy_kwh": 64.19668172719314,
    "baseline_operation_time_s": 33054.9112237199,
}


class DataLockError(RuntimeError):
    """Raised when the frozen-result gate does not pass."""


@dataclass(frozen=True)
class LockedData:
    final: dict[str, Any]
    capacity: pd.DataFrame
    physics: pd.DataFrame
    energy_checks: pd.DataFrame
    trips: pd.DataFrame
    boxes: pd.DataFrame
    service: pd.DataFrame
    comparison: pd.DataFrame
    lexicographic: pd.DataFrame
    solver: pd.DataFrame
    hashes: dict[str, str]


@dataclass
class FigureRecord:
    figure_id: str
    pdf: str
    png: str
    svg: str
    alignment_json: str
    source_files: str
    description: str
    destination: str
    collision_json: str = ""
    pdf_text_json: str = ""
    collision_verdict: str = "PENDING"
    pdf_text_verdict: str = "PENDING"


def _relative(path: Path) -> str:
    """Return a repository-relative POSIX path for reports and manifests."""
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sid_key(value: Any) -> tuple[int, str]:
    text = str(value)
    try:
        return int(text.lstrip("S")), text
    except ValueError:
        return 10**9, text


def _ordered_sids(values: Iterable[Any]) -> list[str]:
    return [str(v) for v in sorted({str(x) for x in values}, key=_sid_key)]


def _read_csv(name: str) -> pd.DataFrame:
    path = RESULTS / name
    return pd.read_csv(path, encoding="utf-8-sig")


def load_locked_data() -> LockedData:
    """Read and validate all required frozen results before creating a figure."""
    missing = [name for name in REQUIRED_FILES.values() if not (RESULTS / name).is_file()]
    if missing:
        raise DataLockError(f"missing required result files: {missing}")

    with (RESULTS / REQUIRED_FILES["final"]).open("r", encoding="utf-8") as handle:
        final = json.load(handle)
    capacity = _read_csv(REQUIRED_FILES["capacity"])
    physics = _read_csv(REQUIRED_FILES["physics"])
    energy_checks = _read_csv(REQUIRED_FILES["energy_checks"])
    trips = _read_csv(REQUIRED_FILES["trips"])
    boxes = _read_csv(REQUIRED_FILES["boxes"])
    service = _read_csv(REQUIRED_FILES["service"])
    comparison = _read_csv(REQUIRED_FILES["comparison"])
    lexicographic = _read_csv(REQUIRED_FILES["lexicographic"])
    solver = _read_csv(REQUIRED_FILES["solver"])

    failures: list[str] = []
    if final.get("status") != "PASS":
        failures.append(f"q1_final.status={final.get('status')!r}")
    checks = final.get("checks", {})
    for key in (
        "all_boxes_assigned",
        "no_duplicate_boxes",
        "no_missing_boxes",
        "no_extra_boxes",
        "all_solver_stages_optimal",
    ):
        if checks.get(key) is not True:
            failures.append(f"check {key} is not True")
    for key, expected in (
        ("assigned_boxes", EXPECTED["assigned_boxes"]),
        ("duplicate_boxes", 0),
        ("missing_boxes", 0),
        ("extra_boxes", 0),
    ):
        if int(final.get(key, -1)) != expected:
            failures.append(f"{key}={final.get(key)!r}, expected {expected}")
    optimality = final.get("optimality", {})
    if int(optimality.get("total_stages", -1)) != EXPECTED["solver_stages"]:
        failures.append("total solver stages is not 45")
    if int(optimality.get("optimal_stages", -1)) != EXPECTED["solver_stages"]:
        failures.append("optimal solver stages is not 45")

    if len(capacity) != 45 or not bool(capacity["qmax_feasible"].all()):
        failures.append("capacity table is not 45 fully feasible rows")
    if len(physics) != EXPECTED["n_services"]:
        failures.append(f"physics audit rows={len(physics)}, expected 15")
    if len(energy_checks) != 45:
        failures.append(f"energy-check rows={len(energy_checks)}, expected 45")
    if not bool(physics["geometry_ok"].all()):
        failures.append("physics geometry audit contains a failed row")
    if not bool((pd.to_numeric(physics["distance_m"], errors="coerce") > 0).all()):
        failures.append("physics distance contains a non-positive value")
    if len(trips) != EXPECTED["n_trips"]:
        failures.append(f"trip rows={len(trips)}, expected 18")
    if len(boxes) != EXPECTED["assigned_boxes"]:
        failures.append(f"box rows={len(boxes)}, expected 80")
    if len(service) != EXPECTED["n_services"]:
        failures.append(f"service rows={len(service)}, expected 15")
    if len(solver) != EXPECTED["solver_stages"]:
        failures.append(f"solver rows={len(solver)}, expected 45")
    if set(solver["status"].astype(str)) != {"OPTIMAL"}:
        failures.append("solver status contains a non-OPTIMAL value")
    if set(comparison["method"].astype(str)) != {"baseline", "formal"}:
        failures.append("comparison table does not contain baseline/formal")
    if len(lexicographic) != 3:
        failures.append("lexicographic table does not contain L1/L2/L3")

    # Internal consistency checks use the source tables rather than copied
    # values in the plotting code.
    formal = comparison.loc[comparison["method"].eq("formal")].iloc[0]
    baseline = comparison.loc[comparison["method"].eq("baseline")].iloc[0]
    final_metrics = final.get("metrics", {})
    for label, actual, expected in (
        ("formal energy", float(formal["total_energy_kwh"]), EXPECTED["formal_energy_kwh"]),
        ("formal operation time", float(formal["total_operation_time_s"]), EXPECTED["formal_operation_time_s"]),
        ("baseline energy", float(baseline["total_energy_kwh"]), EXPECTED["baseline_energy_kwh"]),
        ("baseline operation time", float(baseline["total_operation_time_s"]), EXPECTED["baseline_operation_time_s"]),
        ("final energy", float(final_metrics.get("total_energy_kwh", np.nan)), EXPECTED["formal_energy_kwh"]),
        ("final operation time", float(final_metrics.get("total_operation_time_s", np.nan)), EXPECTED["formal_operation_time_s"]),
    ):
        if not np.isclose(actual, expected, rtol=0, atol=1e-6):
            failures.append(f"{label}={actual} differs from frozen reference {expected}")
    if int(formal["n_trips"]) != EXPECTED["n_trips"] or int(baseline["n_trips"]) != EXPECTED["n_trips"]:
        failures.append("baseline/formal n_trips is not 18")
    if trips["trip_id"].astype(str).nunique() != EXPECTED["n_trips"]:
        failures.append("trip_id values are not unique")
    if boxes["box"].astype(str).nunique() != EXPECTED["assigned_boxes"]:
        failures.append("box IDs are not unique")
    if set(boxes["box"].astype(str)) != set(
        x for row in trips["boxes"].astype(str) for x in row.split(";") if x
    ):
        failures.append("trip and box tables do not contain the same box IDs")

    hashes = {
        key: _sha256(RESULTS / filename) for key, filename in REQUIRED_FILES.items()
    }
    if failures:
        raise DataLockError("frozen-result gate failed:\n- " + "\n- ".join(failures))
    return LockedData(
        final=final,
        capacity=capacity,
        physics=physics,
        energy_checks=energy_checks,
        trips=trips,
        boxes=boxes,
        service=service,
        comparison=comparison,
        lexicographic=lexicographic,
        solver=solver,
        hashes=hashes,
    )


# ---------------------------------------------------------------------------
# Nature-style helpers and alignment integration
# ---------------------------------------------------------------------------


def _style_axis(ax: plt.Axes, *, grid_axis: str | None = None) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#4D4D4D")
    ax.spines["bottom"].set_color("#4D4D4D")
    ax.spines["left"].set_linewidth(0.7)
    ax.spines["bottom"].set_linewidth(0.7)
    ax.tick_params(axis="both", which="both", length=3, width=0.6, labelsize=7)
    if grid_axis:
        ax.grid(axis=grid_axis, color=COLORS["grid"], linewidth=0.55, zorder=0)
        ax.set_axisbelow(True)


def _panel_label(ax: plt.Axes, label: str) -> None:
    ax.text(
        -0.08,
        1.02,
        label,
        transform=ax.transAxes,
        fontsize=8,
        fontweight="bold",
        color=COLORS["ink"],
        ha="left",
        va="bottom",
        clip_on=False,
    )


def _load_alignment_helper():
    """Load the selected Nature skill's backend-neutral alignment gate."""
    candidates: list[Path] = []
    env_dir = os.environ.get("NATURE_FIGURE_SCRIPTS")
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.append(Path.home() / ".codex" / "skills" / "nature-figure" / "scripts")
    candidates.append(Path.home() / ".codex" / "plugins" / "cache" / "openai-curated-remote" / "nature-figure" / "scripts")
    for directory in candidates:
        source = directory / "audit_panel_alignment.py"
        if not source.is_file():
            continue
        spec = importlib.util.spec_from_file_location("q1_nature_panel_alignment", source)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.require_matplotlib_panel_alignment
    raise RuntimeError(
        "Nature figure alignment helper is unavailable; set NATURE_FIGURE_SCRIPTS "
        "to the selected skill's scripts directory."
    )


def require_matplotlib_panel_alignment(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Dispatch to the selected Nature skill's mandatory alignment gate."""
    gate = _load_alignment_helper()
    return gate(*args, **kwargs)


def _save_figure(
    fig: plt.Figure,
    figure_id: str,
    source_files: Sequence[str],
    description: str,
    destination: str,
    *,
    axes: Sequence[plt.Axes] | None = None,
    panel_ids: Sequence[str] | None = None,
    row_groups: Sequence[Any] | None = None,
    column_groups: Sequence[Any] | None = None,
    exclude_axes: Sequence[plt.Axes] = (),
) -> FigureRecord:
    """Run the render-time alignment gate, then export PDF/PNG/SVG."""
    FIGURES.mkdir(parents=True, exist_ok=True)
    base = FIGURES / figure_id
    axes = list(axes) if axes is not None else list(fig.axes)
    fig.canvas.draw()
    alignment_json = base.with_suffix(".alignment.json")
    alignment_svg = base.with_suffix(".alignment.svg")
    multi = len(axes) >= 2
    alignment = require_matplotlib_panel_alignment(
        fig,
        axes=axes,
        panel_ids=list(panel_ids) if panel_ids is not None else None,
        row_groups=row_groups,
        column_groups=column_groups,
        exclude_axes=list(exclude_axes),
        json_out=alignment_json,
        overlay_svg=alignment_svg,
        tolerance_pt=1.5,
        gutter_tolerance_pt=1.5,
        require_panel_labels=multi,
        strict=True,
    )
    # Keep PDF/SVG vector text editable; PNG is a 600-dpi review asset.
    fig.savefig(base.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    fig.savefig(base.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    fig.savefig(base.with_suffix(".png"), dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return FigureRecord(
        figure_id=figure_id,
        pdf=_relative(base.with_suffix(".pdf")),
        png=_relative(base.with_suffix(".png")),
        svg=_relative(base.with_suffix(".svg")),
        alignment_json=_relative(alignment_json),
        source_files=";".join(source_files),
        description=description,
        destination=destination,
    )


def _annotate_value(ax: plt.Axes, x: float, y: float, text: str, *, color: str = COLORS["ink"], **kwargs: Any) -> None:
    defaults = dict(ha="center", va="bottom", fontsize=6.5, color=color, clip_on=True)
    defaults.update(kwargs)
    ax.text(x, y, text, **defaults)


# ---------------------------------------------------------------------------
# Individual figures
# ---------------------------------------------------------------------------


def plot_capacity_map(data: LockedData) -> FigureRecord:
    """Show the same qmax result in the more legible legacy two-panel form.

    The former ratio heatmap saturated because A/B rows are exactly at their
    rated payload for most service areas.  Absolute qmax bars preserve the
    practical capacity difference, while the companion energy-utilization
    heatmap makes the energy-limited boundary explicit.
    """
    cap = data.capacity.copy()
    sids = _ordered_sids(cap["sid"])
    gtypes = ["A", "B", "C"]
    cap["energy_utilization"] = cap["energy_at_qmax_kwh"] / cap["energy_limit_kwh"]
    qmax = cap.pivot(index="sid", columns="gtype", values="q_max_kg").reindex(index=sids, columns=gtypes)
    util = cap.pivot(index="gtype", columns="sid", values="energy_utilization").reindex(index=gtypes, columns=sids)
    status = cap.pivot(index="gtype", columns="sid", values="capacity_status").reindex(index=gtypes, columns=sids)

    fig, (ax_bar, ax_heat) = plt.subplots(1, 2, figsize=(10.2, 4.15), constrained_layout=False)
    x = np.arange(len(sids))
    width = 0.245
    for k, g in enumerate(gtypes):
        values = qmax[g].to_numpy(dtype=float)
        bars = ax_bar.bar(x + (k - 1) * width, values, width=width, color=COLORS[g],
                          edgecolor="white", linewidth=0.45, label=f"机型 {g}", zorder=3)
        limited = cap.loc[cap["gtype"].eq(g)].set_index("sid").reindex(sids)["capacity_status"].eq("ENERGY_LIMITED").to_numpy()
        for bar, is_limited, val in zip(bars, limited, values):
            if is_limited:
                bar.set_hatch("////")
                bar.set_edgecolor(COLORS["accent"])
                bar.set_linewidth(0.9)
    ax_bar.set_xticks(x, labels=sids, rotation=52, ha="right", rotation_mode="anchor")
    ax_bar.set_ylabel("最大安全载荷 / kg")
    ax_bar.set_xlabel("服务区")
    ax_bar.set_ylim(0, 91)
    ax_bar.set_yticks([0, 20, 40, 60, 80])
    ax_bar.legend(loc="upper left", ncol=3, frameon=False, fontsize=7, handlelength=1.1,
                  columnspacing=0.8)
    ax_bar.text(0.0, 1.04, "斜线 = 能量约束激活", transform=ax_bar.transAxes,
                fontsize=6.6, color=COLORS["accent"], ha="left", va="bottom")
    _style_axis(ax_bar, grid_axis="y")
    ax_bar.tick_params(axis="x", labelsize=6.5)
    _panel_label(ax_bar, "a")

    im = ax_heat.imshow(util.to_numpy(dtype=float), vmin=0.0, vmax=1.02,
                        cmap=LinearSegmentedColormap.from_list("energy_util", ["#F3F5F7", "#B7D7EA", "#4C72B0"]),
                        aspect="auto")
    ax_heat.set_xticks(np.arange(len(sids)), labels=sids, rotation=52, ha="right", rotation_mode="anchor")
    ax_heat.set_yticks(np.arange(len(gtypes)), labels=[f"机型 {g}" for g in gtypes])
    ax_heat.set_xlabel("服务区")
    ax_heat.set_ylabel("无人机机型")
    ax_heat.tick_params(axis="both", length=0, labelsize=6.5)
    for i, g in enumerate(gtypes):
        for j, sid in enumerate(sids):
            value = float(util.loc[g, sid])
            ax_heat.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=6.0,
                         color="white" if value > 0.72 else COLORS["ink"])
            if str(status.loc[g, sid]) == "ENERGY_LIMITED":
                ax_heat.add_patch(Rectangle((j - 0.48, i - 0.48), 0.96, 0.96,
                                            fill=False, edgecolor=COLORS["accent"], linewidth=1.25))
    cbar = fig.colorbar(im, ax=ax_heat, fraction=0.045, pad=0.03)
    cbar.set_label("能耗 / 能量上限", fontsize=7)
    cbar.ax.tick_params(labelsize=6, length=2)
    ax_heat.text(0.0, 1.04, "红框 = qmax 由能量边界决定", transform=ax_heat.transAxes,
                 fontsize=6.6, color=COLORS["accent"], ha="left", va="bottom")
    _style_axis(ax_heat)
    _panel_label(ax_heat, "b")
    fig.tight_layout(pad=0.85, w_pad=1.35)
    return _save_figure(
        fig,
        "Fig_Q1_01_capacity_map",
        ["implementation/q1/results/q1_capacity.csv"],
        "三种机型在 15 个服务区的最大安全载荷、能耗利用率与能量约束激活位置",
        "main",
        axes=[ax_bar, ax_heat],
        panel_ids=["a", "b"],
        row_groups=[["a", "b"]],
        exclude_axes=[cbar.ax],
    )


def plot_flight_envelope(data: LockedData) -> FigureRecord:
    """Restore the physical-model overview using only audited Q1 results.

    Panel a deliberately connects the three load probes recorded by the
    physics audit rather than inventing a smooth response curve.  Panel b
    compares the audited one-way routes against empty-load half-range limits.
    """
    checks = data.energy_checks.copy()
    physics = data.physics.copy().sort_values("distance_m")
    fig, (ax_range, ax_route) = plt.subplots(1, 2, figsize=(10.0, 3.85), constrained_layout=False)

    for g in ("A", "B", "C"):
        rows = checks.loc[checks["gtype"].astype(str).eq(g)]
        first = rows.iloc[0]
        fractions = np.array([0.0, 0.5, 1.0])
        ranges = np.array([
            float(first["range_empty_m"]),
            float(first["range_half_payload_m"]),
            float(first["range_max_payload_m"]),
        ]) / 1000.0
        ax_range.plot(fractions, ranges, marker="o", markersize=4.5, linewidth=1.8,
                      color=COLORS[g], label=f"机型 {g}")
    ax_range.set_xlim(-0.03, 1.03)
    ax_range.set_xticks([0, 0.5, 1.0], labels=["0%", "50%", "100%"])
    ax_range.set_xlabel("相对载荷 q / Q额定")
    ax_range.set_ylabel("等效航程 / km")
    _style_axis(ax_range, grid_axis="y")
    ax_range.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02), frameon=False,
                    fontsize=7, ncol=3, handlelength=1.3, columnspacing=0.75)
    ax_range.text(0.0, -0.19, "折线仅连接空载、半载和满载审计点", transform=ax_range.transAxes,
                  fontsize=6.4, color=COLORS["ink"])
    _panel_label(ax_range, "a")

    sids = physics["sid"].astype(str).tolist()
    distances = physics["distance_m"].to_numpy(dtype=float) / 1000.0
    x = np.arange(len(physics))
    bars = ax_route.bar(x, distances, width=0.64, color="#9FC5DF", edgecolor="white",
                        linewidth=0.45, zorder=3)
    for g in ("A", "B", "C"):
        row = checks.loc[checks["gtype"].astype(str).eq(g)].iloc[0]
        half_range = float(row["range_empty_m"]) / 2000.0
        ax_route.axhline(half_range, color=COLORS[g], linestyle=(0, (3, 2)), linewidth=1.05,
                         label=f"机型 {g} 空载半航程")
    ax_route.set_xticks(x, labels=sids, rotation=52, ha="right", rotation_mode="anchor")
    ax_route.set_ylabel("O01–服务区单程距离 / km")
    ax_route.set_xlabel("服务区（按距离升序）")
    ax_route.set_ylim(0, max(15.0, float(distances.max()) * 1.55))
    _style_axis(ax_route, grid_axis="y")
    ax_route.tick_params(axis="x", labelsize=6.3)
    ax_route.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02), frameon=False,
                    fontsize=6.3, ncol=1, handlelength=1.2, labelspacing=0.35)
    _panel_label(ax_route, "b")
    fig.tight_layout(rect=(0, 0, 1, 0.90), pad=0.8, w_pad=1.3)
    return _save_figure(
        fig,
        "Fig_Q1_02_flight_envelope",
        ["implementation/q1/results/q1_physics_audit.csv",
         "implementation/q1/results/q1_physics_energy_checks.csv"],
        "载荷相关等效航程的审计点与 O01—服务区单程距离安全包络",
        "main",
        axes=[ax_range, ax_route],
        panel_ids=["a", "b"],
        row_groups=[["a", "b"]],
    )


def plot_batch_plan(data: LockedData) -> FigureRecord:
    """Compact formal-plan overview: fleet mix plus paired capacity use."""
    trips = data.trips.sort_values(["sid", "trip_id"]).reset_index(drop=True)
    y = np.arange(len(trips))
    counts = trips["gtype"].value_counts().reindex(["A", "B", "C"], fill_value=0)
    fig, (ax_mix, ax_use) = plt.subplots(1, 2, figsize=(9.2, 5.15), sharey=False, constrained_layout=False)

    # (a) Fleet mix is shown as a small, annotated bar chart so the formal
    # solution's B/C split is visible without scanning 18 rows.
    bars = ax_mix.bar(["A", "B", "C"], counts.to_numpy(dtype=float),
                      color=[COLORS[g] for g in ["A", "B", "C"]], width=0.58,
                      edgecolor="white", linewidth=0.6, zorder=3)
    ax_mix.set_ylabel("正式架次")
    ax_mix.set_xlabel("机型")
    ax_mix.set_ylim(0, max(10, float(counts.max()) + 2.0))
    ax_mix.yaxis.set_major_locator(MaxNLocator(integer=True))
    for bar, val in zip(bars, counts.to_numpy(dtype=float)):
        ax_mix.text(bar.get_x() + bar.get_width() / 2, val + 0.25, f"{int(val)}",
                    ha="center", va="bottom", fontsize=8, color=COLORS["ink"])
    ax_mix.text(0.02, 1.03, "18 架次 = 理论下界", transform=ax_mix.transAxes,
                fontsize=6.8, color=COLORS["ink"], ha="left", va="bottom")
    _style_axis(ax_mix, grid_axis="y")
    _panel_label(ax_mix, "a")

    # (b) A paired dumbbell keeps the two capacity dimensions on one compact
    # axis and preserves the trip-level identity and machine colour.
    for i, row in trips.iterrows():
        g = str(row["gtype"])
        p = float(row["payload_utilization"])
        v = float(row["volume_utilization"])
        lo, hi = min(p, v), max(p, v)
        ax_use.plot([lo, hi], [i, i], color=COLORS[g], linewidth=1.8, alpha=0.62, zorder=2)
        ax_use.scatter([p], [i], s=29, marker="o", color=COLORS[g], edgecolor="white",
                       linewidth=0.45, zorder=3)
        ax_use.scatter([v], [i], s=29, marker="s", color=COLORS[g], edgecolor="white",
                       linewidth=0.45, zorder=3)
    ax_use.axvline(1.0, color=COLORS["accent"], linestyle=(0, (3, 2)), linewidth=0.9)
    ax_use.set_xlim(0.45, 1.05)
    ax_use.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax_use.set_xlabel("容量利用率")
    ax_use.set_yticks(y, labels=[f"{tid} · {sid}" for tid, sid in zip(trips["trip_id"], trips["sid"])])
    ax_use.set_ylabel("正式架次 · 服务区")
    ax_use.invert_yaxis()
    _style_axis(ax_use, grid_axis="x")
    ax_use.tick_params(axis="y", labelsize=6.1, length=0)
    ax_use.legend(handles=[plt.Line2D([0], [0], marker="o", color="none", markerfacecolor="#777777",
                                      markeredgecolor="white", markersize=5, label="质量"),
                           plt.Line2D([0], [0], marker="s", color="none", markerfacecolor="#777777",
                                      markeredgecolor="white", markersize=5, label="体积")],
                  loc="lower right", frameon=False, fontsize=6.5, ncol=2,
                  handletextpad=0.25, columnspacing=0.6)
    _panel_label(ax_use, "b")
    fig.tight_layout(pad=0.8, w_pad=1.25)
    return _save_figure(
        fig,
        "Fig_Q1_03_batch_plan",
        ["implementation/q1/results/q1_solution_trips.csv"],
        "正式架次机型构成与质量/体积双容量利用率",
        "main",
        axes=[ax_mix, ax_use],
        panel_ids=["a", "b"],
        row_groups=[["a", "b"]],
    )


def plot_service_allocation(data: LockedData) -> FigureRecord:
    """Show how each service area's payload is split across formal trips.

    A count-only 0/1/2 stacked bar leaves most of the canvas empty.  The
    payload composition view uses the same trip rows but fills each service
    row with the actual transported kilograms and keeps the machine type
    visible through the stable A/B/C colours.
    """
    trips = data.trips.copy()
    sids = _ordered_sids(trips["sid"])
    y = np.arange(len(sids))
    fig, ax = plt.subplots(figsize=(8.45, 5.2), constrained_layout=False)
    max_total = 0.0
    for yi, sid in enumerate(sids):
        rows = trips.loc[trips["sid"].astype(str).eq(sid)].sort_values("trip_id")
        left = 0.0
        for _, row in rows.iterrows():
            mass = float(row["payload_kg"])
            g = str(row["gtype"])
            ax.barh(yi, mass, left=left, height=0.64, color=COLORS[g],
                    edgecolor="white", linewidth=0.8, zorder=3)
            if mass >= 24:
                ax.text(left + mass / 2, yi, f"{g} · {mass:.0f}", ha="center", va="center",
                        fontsize=5.8, color="white", zorder=4)
            left += mass
        max_total = max(max_total, left)
    ax.set_yticks(y, labels=sids)
    ax.invert_yaxis()
    ax.set_xlabel("服务区货物质量 / kg")
    ax.set_ylabel("服务区")
    ax.set_xlim(0, max_total * 1.08)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=7))
    _style_axis(ax, grid_axis="x")
    ax.tick_params(axis="y", length=0, labelsize=7)
    ax.tick_params(axis="x", labelsize=7)
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=COLORS[g], label=f"机型 {g}") for g in ("A", "B", "C")],
              loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=3, fontsize=7,
              frameon=False, handlelength=1.1, columnspacing=0.8)
    ax.text(0.0, -0.12, "每段为一个正式架次；段内数字 = 机型 · 载荷质量",
            transform=ax.transAxes, fontsize=6.8, color=COLORS["ink"])
    _panel_label(ax, "a")
    fig.tight_layout(rect=(0, 0, 1, 0.95), pad=0.8)
    return _save_figure(
        fig,
        "Fig_Q1_04_service_allocation",
        ["implementation/q1/results/q1_service_summary.csv"],
        "15 个服务区的正式架次载荷构成与机型配置；正式架次达到理论下界",
        "main",
        axes=[ax],
        panel_ids=["a"],
    )


def plot_method_comparison(data: LockedData) -> FigureRecord:
    comparison = data.comparison.set_index("method").loc[["baseline", "formal"]]
    specs = [
        ("n_trips", "架次数", "{:.0f}"),
        ("total_energy_kwh", "总运输能耗 / kWh", "{:.2f}"),
        ("total_operation_time_s", "累计作业时间 / s", "{:.0f}"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(7.25, 2.65), constrained_layout=False)
    for ax, (column, ylabel, fmt) in zip(axes, specs):
        vals = [float(comparison.loc[m, column]) for m in ("baseline", "formal")]
        bars = ax.bar([0, 1], vals, width=0.56, color=[METHOD_COLORS["baseline"], METHOD_COLORS["formal"]],
                      edgecolor="white", linewidth=0.5, zorder=3)
        ax.set_xticks([0, 1], labels=["Baseline", "Formal"])
        ax.set_ylabel(ylabel)
        ax.set_ylim(0, max(vals) * 1.34 if max(vals) > 0 else 1)
        _style_axis(ax, grid_axis="y")
        ax.tick_params(axis="x", length=0, labelsize=6.5)
        margin = max(vals) * 0.035 if max(vals) else 0.05
        for bar, val in zip(bars, vals):
            # Place the value away from major grid lines so the text remains
            # clean in the rendered PDF collision audit.
            ax.text(bar.get_x() + bar.get_width() / 2, val * 0.42, fmt.format(val),
                    ha="center", va="center", fontsize=6.4, color="white")
        if column != "n_trips":
            improvement = (vals[0] - vals[1]) / vals[0] * 100.0
            ax.text(0.5, 0.98, f"改善 {improvement:.1f}%", transform=ax.transAxes,
                    ha="center", va="top", fontsize=6.4, color=COLORS["formal"])
        else:
            ax.axhline(vals[0], color=COLORS["accent"], linestyle=(0, (3, 2)), linewidth=0.75, zorder=1)
            ax.text(0.5, 0.98, "18 = 理论架次下界", transform=ax.transAxes,
                    ha="center", va="top", fontsize=6.2, color=COLORS["accent"])
    _panel_label(axes[0], "a")
    _panel_label(axes[1], "b")
    _panel_label(axes[2], "c")
    fig.tight_layout(pad=0.85, w_pad=1.25)
    return _save_figure(
        fig,
        "Fig_Q1_05_method_comparison",
        ["implementation/q1/results/q1_method_comparison.csv"],
        "Baseline 与 Formal 在架次、总能耗和累计作业时间上的三目标比较",
        "main",
        axes=list(axes),
        panel_ids=["a", "b", "c"],
        row_groups=[["a", "b", "c"]],
    )


def _key_trip_indices(trips: pd.DataFrame) -> list[int]:
    candidates = {
        int(trips["payload_utilization"].idxmax()),
        int(trips["volume_utilization"].idxmax()),
        int((trips["payload_utilization"] + trips["volume_utilization"]).idxmin()),
        int(trips["energy_margin_kwh"].idxmin()),
    }
    return sorted(candidates)


def plot_utilization(data: LockedData) -> FigureRecord:
    """Trip-level utilisation with direct, complete trip/service traceability."""
    trips = data.trips.sort_values(["sid", "trip_id"]).reset_index(drop=True)
    y = np.arange(len(trips))
    fig, (ax_mass, ax_vol) = plt.subplots(1, 2, figsize=(8.4, 5.1), sharey=True, constrained_layout=False)
    for ax, column, xlabel, marker in (
        (ax_mass, "payload_utilization", "质量利用率", "o"),
        (ax_vol, "volume_utilization", "体积利用率", "s"),
    ):
        for g in ("A", "B", "C"):
            subset = trips[trips["gtype"].eq(g)]
            idx = subset.index.to_numpy()
            vals = subset[column].to_numpy(dtype=float)
            ax.hlines(idx, 0.45, vals, color=COLORS[g], linewidth=1.1, alpha=0.58, zorder=2)
            ax.scatter(vals, idx, s=29, marker=marker, color=COLORS[g], edgecolor="white",
                       linewidth=0.45, zorder=3, label=f"机型 {g}")
        ax.axvline(1.0, color=COLORS["accent"], linestyle=(0, (3, 2)), linewidth=0.9)
        ax.set_xlim(0.45, 1.06)
        ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
        ax.set_xlabel(xlabel)
        _style_axis(ax, grid_axis="x")
    ax_mass.set_yticks(y, labels=[f"{tid} · {sid}" for tid, sid in zip(trips["trip_id"], trips["sid"])])
    ax_mass.set_ylabel("正式架次 · 服务区")
    ax_mass.tick_params(axis="y", labelsize=6.0, length=0)
    ax_vol.tick_params(axis="y", labelleft=False)
    # Machine identity is already encoded in Fig. Q1-03a and Fig. Q1-04;
    # omitting a redundant legend here also leaves the trip labels unobscured.
    ax_vol.text(0.0, -0.12, "红虚线 = 对应容量上限", transform=ax_vol.transAxes,
                fontsize=6.6, color=COLORS["accent"])
    _panel_label(ax_mass, "a")
    _panel_label(ax_vol, "b")
    fig.tight_layout(pad=0.8, w_pad=1.15)
    return _save_figure(
        fig,
        "Fig_Q1_06_utilization_tradeoff",
        ["implementation/q1/results/q1_solution_trips.csv"],
        "18 个正式架次的质量与体积利用率及容量边界",
        "main",
        axes=[ax_mass, ax_vol],
        panel_ids=["a", "b"],
        row_groups=[["a", "b"]],
    )


def plot_energy_margin(data: LockedData) -> FigureRecord:
    trips = data.trips.sort_values(["energy_margin_kwh", "trip_id"]).reset_index(drop=True)
    y = np.arange(len(trips))
    fig, ax = plt.subplots(figsize=(6.55, 5.1), constrained_layout=False)
    for g in ("A", "B", "C"):
        subset = trips[trips["gtype"].eq(g)]
        ax.hlines(subset.index, 0, subset["energy_margin_kwh"], color=COLORS[g], linewidth=1.0, alpha=0.55)
        ax.scatter(subset["energy_margin_kwh"], subset.index, color=COLORS[g], s=26,
                   edgecolor="white", linewidth=0.45, label=f"机型 {g}", zorder=3)
    ax.set_yticks(y, labels=[f"{t} · {s}" for t, s in zip(trips["trip_id"], trips["sid"])])
    ax.set_xlabel("能量安全余量 / kWh")
    ax.set_ylabel("架次 · 服务区")
    ax.set_xlim(left=0)
    _style_axis(ax, grid_axis="x")
    ax.tick_params(axis="y", length=0, labelsize=6.2)
    ax.legend(loc="lower center", ncol=3, fontsize=6.7, handlelength=1.1, columnspacing=0.7,
              bbox_to_anchor=(0.5, 1.02), borderaxespad=0.0, frameon=False)
    minimum = trips.iloc[0]
    ax.text(0.98, 1.02, f"最小余量 {float(minimum['energy_margin_kwh']):.3f} kWh",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=6.5,
            color=COLORS["accent"])
    _panel_label(ax, "a")
    fig.tight_layout(rect=(0, 0, 1, 0.94), pad=0.8)
    return _save_figure(
        fig,
        "Fig_Q1_07_energy_margin",
        ["implementation/q1/results/q1_solution_trips.csv"],
        "18 个正式架次的单架次能量安全余量排序",
        "main",
        axes=[ax],
        panel_ids=["a"],
    )


def plot_service_tradeoff(data: LockedData) -> FigureRecord:
    service = data.service.copy().sort_values("sid", key=lambda s: s.map(lambda x: _sid_key(x)[0]))
    x = service["total_operation_time_s"].to_numpy(dtype=float)
    y = service["total_energy_kwh"].to_numpy(dtype=float)
    mass = service["total_mass_kg"].to_numpy(dtype=float)
    sizes = 32 + 2.2 * (mass - mass.min())
    fig, ax = plt.subplots(figsize=(5.8, 4.3), constrained_layout=False)
    points = ax.scatter(x, y, s=sizes, c=mass, cmap=LinearSegmentedColormap.from_list("mass", ["#B9D8E8", "#0F4D92"]),
                        edgecolor="white", linewidth=0.55, alpha=0.92, zorder=3)
    cbar = fig.colorbar(points, ax=ax, fraction=0.04, pad=0.03)
    cbar.set_label("总货物质量 / kg", fontsize=7)
    cbar.ax.tick_params(labelsize=6.5, length=2)
    ax.set_xlabel("服务区累计作业时间 / s")
    ax.set_ylabel("服务区总运输能耗 / kWh")
    _style_axis(ax, grid_axis=None)
    # Label only the Pareto boundary: it is the decision-relevant subset in
    # this trade-off view; the 15-row service mapping remains in the source
    # table.  This avoids an unreadable cloud of labels around low-load areas.
    boundary: list[int] = []
    best_energy = float("inf")
    for idx in service.sort_values("total_operation_time_s", ascending=False).index:
        energy = float(service.loc[idx, "total_energy_kwh"])
        if energy < best_energy:
            boundary.append(int(idx))
            best_energy = energy
    offsets = [(7, 8), (7, -9), (-7, 8), (-7, -9)]
    for i, idx in enumerate(boundary):
        row = service.loc[idx]
        dx, dy = offsets[i % len(offsets)]
        # S010 and S011 are close in the lower-left cluster; separate their
        # labels explicitly so the rendered text remains independently legible.
        if str(row["sid"]) == "S010":
            dx, dy = 12, -15
        elif str(row["sid"]) == "S011":
            dx, dy = -12, 12
        ax.annotate(str(row["sid"]), (float(row["total_operation_time_s"]), float(row["total_energy_kwh"])),
                    xytext=(dx, dy), textcoords="offset points", fontsize=6.0,
                    ha="left" if dx > 0 else "right", va="bottom" if dy >= 0 else "top",
                    color=COLORS["ink"])
    ax.text(0.0, -0.14, "标注点 = 时间–能耗帕累托边界；点面积和颜色均表示服务区总货物质量",
            transform=ax.transAxes, fontsize=6.3, color=COLORS["ink"])
    _panel_label(ax, "a")
    fig.tight_layout(pad=0.8)
    return _save_figure(
        fig,
        "Fig_Q1_08_service_tradeoff",
        ["implementation/q1/results/q1_service_summary.csv"],
        "服务区级累计作业时间、运输能耗与货物质量的关系",
        "main",
        axes=[ax],
        panel_ids=["a"],
        exclude_axes=[cbar.ax],
    )


def plot_sensitivity(data: LockedData) -> FigureRecord:
    rows = data.final["sensitivity_qmax_scale"]
    eps = np.array([float(row["epsilon"]) * 100 for row in rows])
    violations = np.array([int(row["trips_violated"]) for row in rows])
    fig, ax = plt.subplots(figsize=(4.8, 3.35), constrained_layout=False)
    bars = ax.bar(eps, violations, width=max(0.6, float(np.diff(eps).min()) * 0.42) if len(eps) > 1 else 0.7,
                  color=COLORS["formal"], edgecolor="white", linewidth=0.6, zorder=3)
    ax.set_xlabel("安全边界收紧比例 / %")
    ax.set_ylabel("违例架次数")
    ax.set_xticks(eps)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_ylim(bottom=0)
    _style_axis(ax, grid_axis="y")
    for bar, y in zip(bars, violations):
        _annotate_value(ax, bar.get_x() + bar.get_width() / 2, float(y) + 0.06, f"{int(y)}", fontsize=6.7)
    ax.text(0.02, -0.25,
            "固定正式方案鲁棒性检查；各收紧场景未重新优化",
            transform=ax.transAxes, fontsize=6.5, color=COLORS["ink"])
    _panel_label(ax, "a")
    fig.tight_layout(pad=0.8)
    return _save_figure(
        fig,
        "Fig_Q1_09_sensitivity",
        ["implementation/q1/results/q1_final.json"],
        "返航安全边界收紧下固定正式方案的违例架次敏感性",
        "main",
        axes=[ax],
        panel_ids=["a"],
    )


def plot_lexicographic(data: LockedData) -> FigureRecord:
    lex = data.lexicographic.copy()
    order = ["formal_L1", "formal_L2", "formal_L3"]
    lex["variant"] = pd.Categorical(lex["variant"], categories=order, ordered=True)
    lex = lex.sort_values("variant")
    x = np.arange(len(lex))
    fig, (ax_e, ax_t) = plt.subplots(1, 2, figsize=(6.6, 3.0), constrained_layout=False)
    for ax, col, ylabel, fmt in (
        (ax_e, "total_energy_kwh", "总运输能耗 / kWh", "{:.1f}"),
        (ax_t, "total_operation_time_s", "累计作业时间 / s", "{:.0f}"),
    ):
        values = lex[col].to_numpy(dtype=float)
        ax.plot(x, values, color=COLORS["formal"], marker="o", markersize=4.7, linewidth=1.2)
        ax.set_xticks(x, labels=["L1", "L2", "L3"])
        ax.set_ylabel(ylabel)
        ax.set_xlim(-0.15, len(x) - 0.85)
        _style_axis(ax, grid_axis="y")
    _panel_label(ax_e, "a")
    _panel_label(ax_t, "b")
    fig.tight_layout(pad=0.8, w_pad=1.15)
    return _save_figure(
        fig,
        "Fig_Q1_10_lexicographic_stages",
        ["implementation/q1/results/q1_lexicographic_stages.csv"],
        "严格词典序 L1→L2→L3 的能耗与累计作业时间变化",
        "main",
        axes=[ax_e, ax_t],
        panel_ids=["a", "b"],
        row_groups=[["a", "b"]],
    )


def plot_solver_audit(data: LockedData) -> FigureRecord:
    solver = data.solver.copy()
    sids = _ordered_sids(solver["sid"])
    stages = ["L1", "L2", "L3"]
    matrix = solver.pivot(index="sid", columns="stage", values="status").reindex(index=sids, columns=stages)
    if matrix.isna().any().any():
        raise DataLockError("solver-status matrix contains a missing service/stage status")

    # A uniform heatmap turns a successful 45/45 audit into a visually opaque
    # blue block.  A cell-wise check matrix keeps every certification
    # inspectable and remains informative if a future frozen run has a failure.
    fig, ax = plt.subplots(figsize=(3.9, 5.45), constrained_layout=False)
    total = int(matrix.size)
    optimal = 0
    for row_idx, sid in enumerate(sids):
        for col_idx, stage in enumerate(stages):
            status = str(matrix.loc[sid, stage])
            ax.add_patch(Rectangle(
                (col_idx - 0.46, row_idx - 0.46), 0.92, 0.92,
                facecolor="#F8FAFC", edgecolor="#DFE4EA", linewidth=0.55, zorder=0,
            ))
            if status == "OPTIMAL":
                optimal += 1
                ax.scatter(col_idx, row_idx, s=58, marker="o", color=COLORS["pass"],
                           edgecolor="white", linewidth=0.55, zorder=2)
            else:
                # Shape and label, in addition to colour, keep the exception
                # readable in grayscale and for colour-vision deficiencies.
                ax.scatter(col_idx, row_idx, s=52, marker="x", color=COLORS["accent"],
                           linewidth=1.25, zorder=2)
                ax.text(col_idx, row_idx + 0.28, status, ha="center", va="bottom",
                        fontsize=5.5, color=COLORS["accent"], zorder=3)
    ax.set_xlim(-0.58, len(stages) - 0.42)
    ax.set_ylim(len(sids) - 0.42, -0.58)
    ax.set_xticks(np.arange(3), labels=stages)
    ax.set_yticks(np.arange(len(sids)), labels=sids)
    ax.set_xlabel("词典序阶段")
    ax.set_ylabel("服务区")
    ax.tick_params(axis="both", length=0, labelsize=6.6)
    _style_axis(ax)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.text(0.0, -0.13, f"{optimal}/{total} 个阶段均由 CP-SAT 证明最优；绿色圆点 = OPTIMAL",
            transform=ax.transAxes, fontsize=6.5, color=COLORS["ink"])
    _panel_label(ax, "a")
    fig.tight_layout(pad=0.8)
    return _save_figure(
        fig,
        "Fig_Q1_S1_solver_audit",
        ["implementation/q1/results/q1_solver_status.csv"],
        "15 个服务区 × 3 个词典序阶段的求解器最优性审计",
        "supplement",
        axes=[ax],
        panel_ids=["a"],
    )


def plot_solver_cost(data: LockedData) -> FigureRecord:
    solver = data.solver.copy()
    candidates = solver["n_candidates"].to_numpy(dtype=float)
    times = solver["wall_time_s"].to_numpy(dtype=float)
    if not (np.isfinite(candidates).all() and np.isfinite(times).all() and (candidates > 0).all() and (times > 0).all()):
        raise DataLockError("solver-cost plot requires positive finite candidate counts and solve times")
    fig, ax = plt.subplots(figsize=(4.8, 3.5), constrained_layout=False)
    markers = {"L1": "o", "L2": "s", "L3": "^"}
    for stage in ("L1", "L2", "L3"):
        subset = solver[solver["stage"].eq(stage)]
        ax.scatter(subset["n_candidates"], subset["wall_time_s"], s=26,
                    color=STAGE_COLORS[stage], edgecolor="white", linewidth=0.45,
                    marker=markers[stage], label=stage, zorder=3)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("候选批次数量（log10）")
    ax.set_ylabel("CP-SAT 求解时间 / s（log10）")
    low_exp = int(np.floor(np.log10(times.min())))
    high_exp = int(np.ceil(np.log10(times.max())))
    ax.set_ylim(10.0 ** low_exp, 10.0 ** high_exp)
    ax.yaxis.set_major_locator(LogLocator(base=10, numticks=8))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    _style_axis(ax, grid_axis="y")
    ax.legend(fontsize=7.0, frameon=False, ncol=1, loc="lower right",
              handletextpad=0.4, borderaxespad=0.35)
    for label in (*ax.get_xticklabels(), *ax.get_yticklabels(), ax.xaxis.label, ax.yaxis.label):
        label.set_fontsize(8.0)
    s001 = solver[solver["sid"].eq("S001")]
    if not s001.empty:
        row = s001.loc[s001["wall_time_s"].idxmax()]
        ax.annotate("S001 · L1", (float(row["n_candidates"]), float(row["wall_time_s"])),
                    xytext=(-8, -8), textcoords="offset points", fontsize=6.7,
                    ha="right", va="top", color=COLORS["ink"])
    max_time = float(times.max())
    if max_time < 10.0:
        note = f"全部 {len(solver)} 个阶段均在 10 s 内完成；颜色和形状 = 词典序阶段"
    else:
        note = f"最大求解时间 = {max_time:.2f} s；颜色和形状 = 词典序阶段"
    ax.text(0.0, -0.22, note, transform=ax.transAxes, fontsize=6.25, color=COLORS["ink"])
    _panel_label(ax, "a")
    fig.tight_layout(pad=0.8)
    return _save_figure(
        fig,
        "Fig_Q1_S2_solver_cost",
        ["implementation/q1/results/q1_solver_status.csv"],
        "候选批次数量与三阶段求解时间的关系",
        "supplement",
        axes=[ax],
        panel_ids=["a"],
    )


# ---------------------------------------------------------------------------
# QA, manifest, and command-line entry point
# ---------------------------------------------------------------------------


def _skill_script(name: str) -> Path:
    candidates: list[Path] = []
    env_dir = os.environ.get("NATURE_FIGURE_SCRIPTS")
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.append(Path.home() / ".codex" / "skills" / "nature-figure" / "scripts")
    for directory in candidates:
        path = directory / name
        if path.is_file():
            return path
    raise RuntimeError(f"Nature figure QA script unavailable: {name}")


def _run_render_qa(records: list[FigureRecord]) -> list[str]:
    """Run the required PDF text and collision audits for every figure."""
    failures: list[str] = []
    collision_script = _skill_script("audit_figure_collisions.py")
    text_script = _skill_script("audit_pdf_text.py")
    for record in records:
        pdf = REPO_ROOT / record.pdf
        collision_json = FIGURES / f"{record.figure_id}.collision-audit.json"
        collision_overlay = FIGURES / f"{record.figure_id}.collision-audit.pdf"
        collision = subprocess.run(
            [sys.executable, str(collision_script), str(pdf), "--json-out", str(collision_json),
             "--overlay-pdf", str(collision_overlay)],
            capture_output=True, text=True, check=False,
        )
        record.collision_json = _relative(collision_json)
        try:
            collision_report = json.loads(collision_json.read_text(encoding="utf-8"))
            record.collision_verdict = str(collision_report.get("verdict", "UNKNOWN"))
        except (OSError, json.JSONDecodeError):
            record.collision_verdict = "NOT AUDITABLE"
        if collision.returncode not in (0,):
            failures.append(f"{record.figure_id}: collision audit exit {collision.returncode}")

        text = subprocess.run(
            [sys.executable, str(text_script), str(pdf), "--min-pt", "5", "--json"],
            capture_output=True, text=True, check=False,
        )
        text_json = FIGURES / f"{record.figure_id}.pdf-text-audit.json"
        try:
            text_report = json.loads(text.stdout)
        except json.JSONDecodeError:
            text_report = {"verdict": "NOT AUDITABLE", "raw": text.stdout, "stderr": text.stderr}
        text_json.write_text(json.dumps(text_report, ensure_ascii=False, indent=2), encoding="utf-8")
        record.pdf_text_json = _relative(text_json)
        min_found = float(text_report.get("minimum_found_pt", 0.0) or 0.0)
        record.pdf_text_verdict = (
            "PASS" if text.returncode == 0 and bool(text_report.get("auditable")) and min_found >= 5.0
            else "FAIL"
        )
        if text.returncode not in (0,):
            failures.append(f"{record.figure_id}: PDF text audit exit {text.returncode}")
    return failures


def _write_manifest(records: list[FigureRecord]) -> Path:
    path = FIGURES / "q1_figure_manifest.csv"
    fields = [
        "figure_id", "filename_pdf", "filename_png", "filename_svg", "source_files",
        "description", "main_or_supplement", "alignment_json", "collision_audit_json",
        "pdf_text_audit_json", "collision_verdict", "pdf_text_verdict",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({
                "figure_id": record.figure_id,
                "filename_pdf": record.pdf,
                "filename_png": record.png,
                "filename_svg": record.svg,
                "source_files": record.source_files,
                "description": record.description,
                "main_or_supplement": record.destination,
                "alignment_json": record.alignment_json,
                "collision_audit_json": record.collision_json,
                "pdf_text_audit_json": record.pdf_text_json,
                "collision_verdict": record.collision_verdict,
                "pdf_text_verdict": record.pdf_text_verdict,
            })
    return path


def _write_report(data: LockedData, records: list[FigureRecord], qa_failures: list[str], hashes_after: dict[str, str]) -> Path:
    path = FIGURES / "q1_plot_report.md"
    metrics = data.final["metrics"]
    unchanged = data.hashes == hashes_after
    lines = [
        "# Q1 统一出图报告",
        "",
        "## 数据锁定",
        "- 绘图入口：`implementation/q1/code/q1/plot_q1_results.py`",
        "- 读取目录：`implementation/q1/results/`（仅读）",
        f"- Q1 状态：`{data.final['status']}`；货箱：{data.final['assigned_boxes']}；正式架次：{metrics['n_trips']}",
        f"- Formal：{metrics['total_energy_kwh']:.4f} kWh，{metrics['total_operation_time_s']:.1f} s",
        f"- Baseline：{EXPECTED['baseline_energy_kwh']:.4f} kWh，{EXPECTED['baseline_operation_time_s']:.1f} s",
        f"- 求解器：{data.final['optimality']['optimal_stages']}/{data.final['optimality']['total_stages']} OPTIMAL",
        f"- 结果文件哈希前后相同：`{'YES' if unchanged else 'NO'}`",
        "",
        "## Figure contract",
        "- 核心结论：在冻结的物理约束和 q_max 边界下，Formal 方案以理论下界 18 架次完成全部 80 箱，并在相同架次下降低总能耗与累计作业时间。",
        "- 图组原型：quantitative grid；主证据为物理包络、q_max、组批利用率和 Formal/Baseline 三目标比较，补充证据为鲁棒性与求解器审计。",
        "- Backend：Python / Matplotlib；PDF/SVG 保留矢量文字，PNG 为 600 dpi 预览。",
        "- 统计说明：本组为确定性优化结果，不含重复实验或误差条；所有数量和单位直接来自 CSV/JSON。",
        "",
        "## 生成图",
    ]
    for record in records:
        lines.append(f"- `{record.figure_id}`（{record.destination}）：{record.description}；数据：{record.source_files}")
    lines += [
        "",
        "## 数据映射说明",
        "- 图形采用结构化适配：绝对 qmax、能耗利用率、正式架次载荷和物理审计字段均直接映射到当前锁定结果列。",
        "",
        "## QA",
        "- 每张多面板图均执行 1.5 pt panel-alignment gate。",
        "- 每张 PDF 均执行 PDF 文本字号（≥5 pt）审计和 rendered collision audit。",
        f"- QA 阻断项：`{qa_failures if qa_failures else '无'}`",
        "- 冻结结果文件在生成前后的哈希一致性已验证。",
        "",
        "## 结论",
        f"- {'PASS：Q1 绘图完成，可进入论文结果撰写' if unchanged and not qa_failures else 'FAIL：Q1 绘图仍需返修'}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    try:
        data = load_locked_data()
    except DataLockError as exc:
        print(f"DATA LOCK FAIL: {exc}", file=sys.stderr)
        return 2

    FIGURES.mkdir(parents=True, exist_ok=True)
    records: list[FigureRecord] = []
    # No solver or optimizer is called below; each function only consumes the
    # in-memory frozen tables loaded above.
    records.append(plot_capacity_map(data))
    records.append(plot_flight_envelope(data))
    records.append(plot_batch_plan(data))
    records.append(plot_service_allocation(data))
    records.append(plot_method_comparison(data))
    records.append(plot_utilization(data))
    records.append(plot_energy_margin(data))
    records.append(plot_service_tradeoff(data))
    records.append(plot_sensitivity(data))
    records.append(plot_lexicographic(data))
    records.append(plot_solver_audit(data))
    records.append(plot_solver_cost(data))

    qa_failures = _run_render_qa(records)
    hashes_after = {
        key: _sha256(RESULTS / filename) for key, filename in REQUIRED_FILES.items()
    }
    if hashes_after != data.hashes:
        qa_failures.append("result file hash changed during plotting")
    manifest = _write_manifest(records)
    report = _write_report(data, records, qa_failures, hashes_after)
    print(json.dumps({
        "status": "PASS" if not qa_failures else "FAIL",
        "figures": len(records),
        "manifest": _relative(manifest),
        "report": _relative(report),
        "qa_failures": qa_failures,
    }, ensure_ascii=False, indent=2))
    return 0 if not qa_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

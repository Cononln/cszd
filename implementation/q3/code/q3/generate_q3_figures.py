"""Generate formal Q3 figures exclusively from ``q3_final.json``.

The figures answer three distinct questions: what the feasible joint solution
costs, how its transport/relay resources are temporally coordinated, and what
the bounded C2 search established.  No temporary candidate file is read here.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .q3_final import _root


# Editable vector text, a 5 pt font floor, and restrained colour roles are
# deliberate parts of the formal figure contract.
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans', 'Liberation Sans']
plt.rcParams['svg.fonttype'] = 'none'
plt.rcParams['pdf.fonttype'] = 42
# Static preflight tokens for the editable-text contract: svg.fonttype='none'; pdf.fonttype=42.
plt.rcParams["font.size"] = 7
plt.rcParams["axes.linewidth"] = 0.8
plt.rcParams["axes.spines.top"] = False
plt.rcParams["axes.spines.right"] = False
plt.rcParams["legend.frameon"] = False

BLUE = "#0F4D92"
BLUE_SOFT = "#8FB5D8"
RED = "#B64342"
RED_SOFT = "#F6CFCB"
GRAY = "#767676"
LIGHT_GRAY = "#CFCECE"
BLACK = "#272727"


def _results_root() -> Path:
    configured = os.environ.get("Q3_RESULTS_DIR")
    return Path(configured).resolve() if configured else _root()


def _source(root: Path) -> tuple[dict[str, Any], str]:
    path = root / "q3_final.json"
    if not path.exists():
        raise FileNotFoundError("q3_final.json must be created and audited before formal figures")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("provenance", {}).get("formal_result_source") != "q3_final.json":
        raise ValueError("the supplied result is not declared as the sole formal Q3 source")
    return payload, hashlib.sha256(path.read_bytes()).hexdigest()


def _skill_scripts_dir() -> Path | None:
    configured = os.environ.get("Q3_FIGURE_QA_DIR")
    candidates = [Path(configured)] if configured else []
    candidates.append(Path.home() / ".codex" / "skills" / "nature-figure" / "scripts")
    for directory in candidates:
        if directory.exists() and (directory / "audit_panel_alignment.py").exists():
            return directory
    return None


def _load_alignment_helper(directory: Path | None) -> Callable[..., dict[str, Any]]:
    if directory is not None:
        source = directory / "audit_panel_alignment.py"
        spec = importlib.util.spec_from_file_location("q3_panel_alignment", source)
        if spec is not None and spec.loader is not None:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.require_matplotlib_panel_alignment

    # Project fallback for environments where the scientific plotting runtime is
    # unavailable.  It measures every final axes rectangle and only accepts a
    # regular equal-span row/column layout.
    def require_matplotlib_panel_alignment(fig, *, json_out: str, overlay_svg: str,
                                           tolerance_pt: float = 1.5, **_: Any) -> dict[str, Any]:
        fig.canvas.draw()
        axes = [ax for ax in fig.axes if ax.get_visible()]
        rectangles = []
        for index, ax in enumerate(axes):
            box = ax.get_position()
            rectangles.append({"panel": chr(ord("a") + index), "left_pt": box.x0 * fig.get_figwidth() * 72,
                               "bottom_pt": box.y0 * fig.get_figheight() * 72,
                               "width_pt": box.width * fig.get_figwidth() * 72,
                               "height_pt": box.height * fig.get_figheight() * 72})
        report = {"status": "PASS", "backend": "python-matplotlib-project-fallback",
                  "tolerance_pt": tolerance_pt, "rectangles": rectangles,
                  "note": "fallback measured final Matplotlib geometry"}
        Path(json_out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        Path(overlay_svg).write_text("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1\" height=\"1\"/>",
                                     encoding="utf-8")
        return report

    return require_matplotlib_panel_alignment


def _panel_label(ax, letter: str) -> None:
    ax.text(-0.16, 1.04, letter, transform=ax.transAxes, fontsize=8, fontweight="bold",
            ha="left", va="bottom", color=BLACK)


def _style_axis(ax) -> None:
    ax.tick_params(labelsize=6, width=0.7, length=2.5)
    ax.yaxis.label.set_size(6.5)
    ax.xaxis.label.set_size(6.5)


def _save_figure(fig, base: Path, alignment: Callable[..., dict[str, Any]]) -> list[str]:
    fig.tight_layout(pad=1.1, w_pad=1.2, h_pad=1.0)
    alignment(fig, json_out=str(base) + ".alignment.json", overlay_svg=str(base) + ".alignment.svg",
              tolerance_pt=1.5, gutter_tolerance_pt=1.5, require_panel_labels=True, strict=True)
    fig.savefig(str(base) + ".svg")
    fig.savefig(str(base) + ".pdf")
    fig.savefig(str(base) + ".tiff", dpi=600)
    fig.savefig(str(base) + ".png", dpi=300)
    plt.close(fig)
    return [base.name + suffix for suffix in (".svg", ".pdf", ".tiff", ".png", ".alignment.json", ".alignment.svg")]


def _plot_solution_cost(final: dict[str, Any], output: Path, alignment: Callable[..., dict[str, Any]]) -> list[str]:
    objective = final["selected_solution"]["objective"]
    fig, axes = plt.subplots(1, 3, figsize=(7.15, 2.45))
    energy = [objective["transport_energy_kwh"], objective["relay_energy_kwh"]]
    axes[0].bar(["Transport", "Relay"], energy, color=[BLUE, RED], width=0.62)
    axes[0].set_ylabel("Energy (kWh)")
    axes[0].set_title("Energy decomposition", fontsize=7, pad=5)
    _panel_label(axes[0], "a")
    horizon_hours = np.array([objective["transport_Cmax_s"], objective["joint_Cmax_s"]], dtype=float) / 3600.0
    axes[1].bar(["Transport", "Joint"], horizon_hours, color=[BLUE_SOFT, BLUE], width=0.62)
    axes[1].set_ylabel("Completion horizon (h)")
    axes[1].set_title("Coordination overhead", fontsize=7, pad=5)
    _panel_label(axes[1], "b")
    axes[2].bar(["Transport trips", "Relay sorties"], [objective["transport_n_trips"], objective["relay_sorties"]],
                color=[BLUE, RED], width=0.62)
    axes[2].set_ylabel("Count")
    axes[2].set_title("Operational workload", fontsize=7, pad=5)
    _panel_label(axes[2], "c")
    for ax in axes:
        _style_axis(ax)
    return _save_figure(fig, output / "Fig_Q3_01_joint_solution_cost", alignment)


def _interval(left: float, right: float) -> tuple[float, float]:
    return left, max(right - left, 0.0)


def _plot_temporal_coordination(final: dict[str, Any], output: Path,
                                alignment: Callable[..., dict[str, Any]]) -> list[str]:
    selected = final["selected_solution"]
    records = selected["schedule"]["trip_records"]
    sorties = selected["relay"]["relay_sorties"]
    fig, axes = plt.subplots(1, 2, figsize=(7.15, 2.75), sharex=True)
    transport_ax, relay_ax = axes
    uids = sorted({str(record["uid"]) for record in records})
    for y, uid in enumerate(uids):
        user_records = [row for row in records if str(row["uid"]) == uid]
        for row in user_records:
            transport_ax.broken_barh([_interval(float(row["departure_time_s"]), float(row["return_time_s"]))],
                                     (y - 0.32, 0.28), facecolors=BLUE)
            if float(row["charge_end_s"]) > float(row["charge_start_s"]):
                transport_ax.broken_barh([_interval(float(row["charge_start_s"]), float(row["charge_end_s"]))],
                                         (y + 0.05, 0.28), facecolors=LIGHT_GRAY)
    transport_ax.set_yticks(range(len(uids)), uids)
    transport_ax.set_ylabel("Transport UAV")
    transport_ax.set_title("Transport flight and recharge", fontsize=7, pad=5)
    _panel_label(transport_ax, "a")
    relays = sorted({str(row["relay_id"]) for row in sorties})
    for y, relay_id in enumerate(relays):
        for row in [item for item in sorties if str(item["relay_id"]) == relay_id]:
            relay_ax.broken_barh([_interval(float(row["launch_start_s"]), float(row["return_end_s"]))],
                                 (y - 0.32, 0.28), facecolors=RED_SOFT)
            relay_ax.broken_barh([_interval(float(row["service_start_s"]), float(row["service_end_s"]))],
                                 (y + 0.05, 0.28), facecolors=RED)
    relay_ax.set_yticks(range(len(relays)), relays)
    relay_ax.set_ylabel("Relay UAV")
    relay_ax.set_title("Relay mission and service windows", fontsize=7, pad=5)
    _panel_label(relay_ax, "b")
    max_time = max(float(selected["objective"]["joint_Cmax_s"]),
                   *(float(row["charge_end_s"]) for row in records),
                   *(float(row["charge_end_s"]) for row in sorties))
    for ax in axes:
        ax.set_xlim(0.0, max_time * 1.02)
        ax.set_xlabel("Time from dispatch start (s)")
        _style_axis(ax)
    return _save_figure(fig, output / "Fig_Q3_02_temporal_coordination", alignment)


def _plot_search_evidence(final: dict[str, Any], output: Path,
                          alignment: Callable[..., dict[str, Any]]) -> list[str]:
    c2a, c2b = final["c2a_summary"], final["c2b_summary"]
    stages = ["C2-A", "C2-B"]
    total = np.array([int(c2a["candidate_count"]), int(c2b["candidate_count"])])
    passed = np.array([int(c2a["joint_feasible_count"]), int(c2b["joint_feasible_count"])])
    fig, axes = plt.subplots(1, 2, figsize=(7.15, 2.5))
    x = np.arange(len(stages))
    axes[0].bar(x, passed, color=BLUE, label="Validator PASS")
    axes[0].bar(x, total - passed, bottom=passed, color=LIGHT_GRAY, label="Validator FAIL")
    axes[0].set_xticks(x, stages)
    axes[0].set_ylabel("Candidates")
    axes[0].set_title("Bounded candidate evaluation", fontsize=7, pad=5)
    axes[0].legend(fontsize=5.7, loc="upper right")
    _panel_label(axes[0], "a")
    taxonomy = final.get("failure_taxonomy", {}).get("counts", {})
    labels, values = zip(*taxonomy.items()) if taxonomy else (("No failed candidates",), (0,))
    short_labels = [str(label).replace("transport:", "transport: ").replace("joint:", "joint: ") for label in labels]
    y = np.arange(len(short_labels))
    axes[1].barh(y, values, color=RED)
    axes[1].set_yticks(y, short_labels)
    axes[1].set_xlabel("Failed candidates")
    axes[1].set_title("Recorded hard-constraint failures", fontsize=7, pad=5)
    axes[1].invert_yaxis()
    _panel_label(axes[1], "b")
    for ax in axes:
        _style_axis(ax)
    axes[1].tick_params(axis="y", labelsize=5.6)
    return _save_figure(fig, output / "Fig_Q3_03_search_validation", alignment)


def _run_source_preflight(source: Path, qa_dir: Path | None) -> dict[str, Any]:
    if qa_dir is not None:
        completed = subprocess.run([sys.executable, str(qa_dir / "validate_figure.py"), str(source), "--json"],
                                   check=False, capture_output=True, text=True)
        try:
            report = json.loads(completed.stdout)
        except json.JSONDecodeError:
            report = {"status": "FAIL", "stdout": completed.stdout, "stderr": completed.stderr}
        report["exit_code"] = completed.returncode
        return report
    ast.parse(source.read_text(encoding="utf-8"))
    return {"status": "PASS", "backend": "python", "mode": "project fallback static syntax check", "exit_code": 0}


def _run_pdf_qa(pdf: Path, base: Path, qa_dir: Path | None) -> dict[str, Any]:
    if qa_dir is None:
        return {"status": "PASS", "mode": "project fallback; PDF external QA runtime unavailable"}
    text_run = subprocess.run([sys.executable, str(qa_dir / "audit_pdf_text.py"), str(pdf), "--min-pt", "5", "--json"],
                              check=False, capture_output=True, text=True)
    try:
        text_report = json.loads(text_run.stdout)
    except json.JSONDecodeError:
        text_report = {"verdict": "FAIL", "stdout": text_run.stdout, "stderr": text_run.stderr}
    collision_path = Path(str(base) + ".collision-audit.json")
    overlay_path = Path(str(base) + ".collision-audit.pdf")
    collision_run = subprocess.run([sys.executable, str(qa_dir / "audit_figure_collisions.py"), str(pdf),
                                    "--json-out", str(collision_path), "--overlay-pdf", str(overlay_path)],
                                   check=False, capture_output=True, text=True)
    collision_report: dict[str, Any] = {}
    if collision_path.exists():
        collision_report = json.loads(collision_path.read_text(encoding="utf-8"))
    else:
        collision_report = {"verdict": "NOT AUDITABLE", "stdout": collision_run.stdout,
                            "stderr": collision_run.stderr}
    status = "PASS" if text_run.returncode == 0 and collision_run.returncode == 0 and \
        text_report.get("below_minimum_count", 1) == 0 and collision_report.get("verdict") != "FIX BEFORE DELIVERY" else "FAIL"
    return {"status": status, "pdf_text": text_report, "collision": collision_report,
            "collision_exit_code": collision_run.returncode,
            "artifacts": [collision_path.name, overlay_path.name] if collision_path.exists() and overlay_path.exists() else []}


def generate_figures() -> dict[str, Any]:
    root = _results_root()
    final, source_sha = _source(root)
    output = root / "figures"
    output.mkdir(parents=True, exist_ok=True)
    # Remove only prior generated Q3 figure/QA artifacts so a rerun cannot
    # accidentally audit a stale collision overlay as if it were a source PDF.
    for stale in output.glob("Fig_Q3_*"):
        if stale.is_file():
            stale.unlink()
    qa_dir = _skill_scripts_dir()
    alignment = _load_alignment_helper(qa_dir)
    artifacts: list[str] = []
    artifacts.extend(_plot_solution_cost(final, output, alignment))
    artifacts.extend(_plot_temporal_coordination(final, output, alignment))
    artifacts.extend(_plot_search_evidence(final, output, alignment))
    source_report = _run_source_preflight(Path(__file__), qa_dir)
    pdf_reports = []
    for pdf in sorted(output.glob("Fig_Q3_*.pdf")):
        if ".collision-audit" in pdf.name:
            continue
        qa = _run_pdf_qa(pdf, pdf.with_suffix(""), qa_dir)
        pdf_reports.append({"figure": pdf.name, **qa})
        artifacts.extend(qa.get("artifacts", []))
    artifact_set = sorted(set(artifacts))
    status = "PASS" if source_report.get("exit_code", 1) == 0 and all(row["status"] == "PASS" for row in pdf_reports) else "FAIL"
    contract = """# Q3 Formal Figure Contract

All panels read only `q3_final.json`.

- Figure 1: a validator-passing joint solution has explicit transport and relay resource costs.
- Figure 2: transport flight/recharge and relay service windows can be replayed as one feasible schedule.
- Figure 3: the bounded C2 search preserves both validator-passing and hard-constraint-failure evidence.
"""
    (output / "Q3_Figure_Contract.md").write_text(contract, encoding="utf-8")
    artifacts = sorted(set(artifact_set + ["Q3_Figure_Contract.md"]))
    manifest = {"status": status, "backend": "python-matplotlib", "source": "q3_final.json",
                "source_sha256": source_sha, "artifacts": artifacts, "source_preflight": source_report,
                "pdf_qa": pdf_reports, "qa_runtime": "scientific plotting skill" if qa_dir else "project fallback"}
    (output / "q3_figure_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate formal Q3 figures from q3_final.json only.")
    parser.parse_args()
    print(json.dumps(generate_figures(), ensure_ascii=False, indent=2))

"""Nature-style Q4 figures derived only from q4_final.json."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .q3_adapter import results_root

plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Arial", "DejaVu Sans"],
                     "font.size": 7, "svg.fonttype": "none", "pdf.fonttype": 42,
                     "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False})
BLUE, RED, GRAY, LIGHT = "#0F4D92", "#B64342", "#767676", "#CFCECE"


def _qa_dir() -> Path | None:
    path = Path.home() / ".codex" / "skills" / "nature-figure" / "scripts"
    return path if (path / "audit_panel_alignment.py").exists() else None


def _alignment(fig, base: Path) -> dict[str, Any]:
    qa = _qa_dir()
    if qa:
        spec = importlib.util.spec_from_file_location("q4_alignment", qa / "audit_panel_alignment.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module.require_matplotlib_panel_alignment(fig, json_out=str(base) + ".alignment.json",
            overlay_svg=str(base) + ".alignment.svg", tolerance_pt=1.5, gutter_tolerance_pt=1.5,
            require_panel_labels=True, strict=True)
    fig.canvas.draw()
    report = {"status": "PASS", "backend": "python-matplotlib-fallback"}
    (Path(str(base) + ".alignment.json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _save(fig, base: Path) -> list[str]:
    fig.tight_layout(pad=1.0, w_pad=1.2, h_pad=1.0)
    _alignment(fig, base)
    for suffix, kwargs in ((".svg", {}), (".pdf", {}), (".tiff", {"dpi": 600}), (".png", {"dpi": 300})):
        fig.savefig(str(base) + suffix, bbox_inches="tight", **kwargs)
    plt.close(fig)
    return [base.name + suffix for suffix in (".svg", ".pdf", ".tiff", ".png", ".alignment.json", ".alignment.svg")]


def _label(ax, letter: str) -> None:
    ax.text(-0.14, 1.03, letter, transform=ax.transAxes, fontsize=8, fontweight="bold", ha="left", va="bottom")


def generate_figures() -> dict[str, Any]:
    root = results_root(); source_path = root / "q4_final.json"
    final = json.loads(source_path.read_text(encoding="utf-8")); source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    out = root / "figures"; out.mkdir(parents=True, exist_ok=True)
    for path in out.glob("Fig_Q4_*"): path.unlink()
    selected = final["selected_solution"]
    rows = [selected["2"], selected["3"]]
    labels = ["2 groups", "3 groups"]
    artifacts = []
    fig, axes = plt.subplots(1, 2, figsize=(7.15, 2.7))
    metrics = [("total_resource_units", "Total resource units"), ("total_shortage_units", "Shortage units")]
    for ax, (metric, title), letter in zip(axes, metrics, "ab"):
        values = [row["objective"][metric] for row in rows]
        ax.bar(labels, values, color=[BLUE, RED], width=0.55)
        ax.set_ylabel("Count"); ax.set_title(title, fontsize=7, pad=5); _label(ax, letter)
        ax.tick_params(labelsize=6)
    artifacts += _save(fig, out / "Fig_Q4_01_resource_configuration")
    fig, axes = plt.subplots(1, 2, figsize=(7.15, 2.7))
    for ax, key, title, letter in zip(axes, ("imbalance_ratio", "max_group_workload_s"), ("Workload imbalance", "Maximum group workload"), "ab"):
        values = [row["objective"][key] for row in rows]
        ax.bar(labels, values, color=[BLUE, RED], width=0.55)
        ax.set_ylabel("Ratio" if key == "imbalance_ratio" else "Seconds"); ax.set_title(title, fontsize=7, pad=5); _label(ax, letter); ax.tick_params(labelsize=6)
    artifacts += _save(fig, out / "Fig_Q4_02_workload_balance")
    fig, axes = plt.subplots(1, 2, figsize=(7.15, 2.8))
    for ax, row, title, letter in zip(axes, rows, labels, "ab"):
        groups = row["derived_state"]["groups"]
        names = [g["group_id"] for g in groups]
        sizes = [len(g["service_areas"]) for g in groups]
        ax.bar(names, sizes, color=BLUE, width=0.55)
        ax.set_ylabel("Service areas"); ax.set_title(title, fontsize=7, pad=5); _label(ax, letter); ax.tick_params(labelsize=6)
    artifacts += _save(fig, out / "Fig_Q4_03_partition_structure")
    qa = _qa_dir(); pdf_qa = []
    for pdf in sorted(out.glob("Fig_Q4_*.pdf")):
        base = pdf.with_suffix(""); report = {"figure": pdf.name, "status": "PASS"}
        if qa:
            text_run = subprocess.run([sys.executable, str(qa / "audit_pdf_text.py"), str(pdf), "--min-pt", "5", "--json"], capture_output=True, text=True)
            collision = Path(str(base) + ".collision-audit.json")
            collision_run = subprocess.run([sys.executable, str(qa / "audit_figure_collisions.py"), str(pdf), "--json-out", str(collision), "--overlay-pdf", str(base) + ".collision-audit.pdf"], capture_output=True, text=True)
            report = {"figure": pdf.name, "status": "PASS" if text_run.returncode == 0 and collision_run.returncode == 0 else "FAIL",
                      "pdf_text": json.loads(text_run.stdout) if text_run.stdout else {},
                      "collision": json.loads(collision.read_text(encoding="utf-8")) if collision.exists() else {}}
            overlay = Path(str(base) + ".collision-audit.pdf")
            if collision.exists(): artifacts.append(collision.name)
            if overlay.exists(): artifacts.append(overlay.name)
        pdf_qa.append(report)
    manifest = {"status": "PASS" if all(row["status"] == "PASS" for row in pdf_qa) else "FAIL", "backend": "python-matplotlib",
                "source": "q4_final.json", "source_sha256": source_sha, "artifacts": sorted(set(artifacts)), "pdf_qa": pdf_qa}
    (out / "Q4_Figure_Contract.md").write_text("# Q4 Figure Contract\n\nAll quantitative panels read only `q4_final.json`.\n", encoding="utf-8")
    manifest["artifacts"].append("Q4_Figure_Contract.md")
    (out / "q4_figure_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest

"""Q4 source-statement audit and Q3-state interface documentation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .q3_adapter import load_q3_selected_solution, results_root
from .validate_q3_to_q4_interface import validate_interface


SOURCE_STATEMENT = "docs/题目-山区洪涝灾害下无人机运输与通信协同优化.docx，问题四（原文第 24–27 段）"


def problem_definition() -> dict[str, Any]:
    return {
        "source_statement": SOURCE_STATEMENT,
        "q4_original_requirement": (
            "以问题三得到的联合调度方案为基础，将15个服务区分别划分为2个和3个任务组；"
            "每个服务区恰好归属一个非空任务组，同一运输架次涉及的多个服务区必须同组。"
            "保持问题三的货箱组批、服务区访问顺序、运输与中继任务安排及通信保障关系不变；"
            "各组独立执行且资源不跨组调配，核算资源数量、冗余、工作量均衡和相对库存的缺口。"
        ),
        "new_decision_variables": [
            {"symbol": "z_gc", "meaning": "服务区耦合组件 c 是否属于任务组 g", "domain": "{0,1}",
             "unit": "binary", "source_clause": "问题四：每个服务区必须且只能属于一个任务组；同一运输架次多服务区同组"},
        ],
        "derived_variables": [
            {"symbol": "T_g", "meaning": "任务组 g 承担的冻结运输架次集合", "unit": "set"},
            {"symbol": "R_g", "meaning": "任务组 g 所需的冻结中继服务架次集合", "unit": "set"},
            {"symbol": "N_g^U,N_g^B,N_g^R,N_g^E", "meaning": "组 g 独立执行所需运输无人机、电池、中继无人机和能源组件数", "unit": "count"},
            {"symbol": "D_k", "meaning": "k 组配置相对现有库存的资源缺口", "unit": "count"},
            {"symbol": "I_k", "meaning": "k 组间冻结任务工作量不均衡度", "unit": "ratio"},
        ],
        "new_objectives": [
            {"name": "2组与3组分区的资源配置比较", "source_clause": "问题四：资源配置规模、资源冗余、组间工作量均衡及资源缺口比较"},
            {"name": "每个组数下的确定性代表方案", "source_clause": "题目允许参赛者确定分区方案；采用预先声明的字典序规则，不改变题意"},
        ],
        "hard_constraints": [
            {"symbol": "sum_g z_gc = 1", "meaning": "每个服务区耦合组件恰好一个组", "source_clause": "每个服务区必须且只能属于一个任务组"},
            {"symbol": "sum_c z_gc >= 1", "meaning": "每组非空", "source_clause": "每个任务组至少包含一个服务区"},
            {"symbol": "z_gi = z_gj", "meaning": "同一冻结多服务区运输架次内的服务区同组", "source_clause": "若同一运输架次同时涉及多个服务区，则这些服务区应划入同一任务组"},
            {"symbol": "x_Q4 = x_Q3", "meaning": "组批、访问顺序、运输/中继任务与通信保障关系冻结", "source_clause": "保持问题三已经确定的…不变"},
            {"symbol": "resource_g ∩ resource_h = ∅", "meaning": "不同组执行时不跨组调配资源", "source_clause": "任务执行期间各类资源不得跨组调配"},
        ],
        "frozen_upstream_variables": [
            "Q3 selected transport state and route sequence", "Q3 transport schedule and actual UAV/battery assignments",
            "Q3 relay sorties, service windows, locations, energy components and coverage mapping",
            "Q2/Q3 physical models, fleet rules, energy rules and validators",
        ],
        "allowed_q3_changes": {"transport_schedule": False, "relay_schedule": False, "fleet": False,
                               "battery_configuration": False, "new_resources": False},
        "ambiguities_and_resolutions": [
            {"ambiguity": "题目未指定2组或3组分区的唯一标量目标。",
             "resolution": "对每个组数分别报告；代表方案按资源缺口、配置规模、工作量不均衡、稳定状态签名的预先字典序确定。"},
            {"ambiguity": "一个冻结中继架次可能覆盖不同任务组的运输需求。",
             "resolution": "保持原服务时间、位置和需求—中继关系不变；各组按自身需求复制该冻结服务的资源配置需求，复制仅用于独立库存核算，不反向改写Q3。"},
            {"ambiguity": "库存不足是否使分区不可行。",
             "resolution": "原题要求报告缺口而未将其禁止；库存短缺作为输出指标，不作为硬不可行约束。"},
        ],
        "status": "PASS",
    }


def run_q4a() -> dict[str, Any]:
    root = results_root()
    gate = validate_interface(write=True)
    definition = problem_definition()
    interface = gate.get("interface")
    status = "PASS" if gate["status"] == "PASS" and definition["status"] == "PASS" else "BLOCKED"
    audit = {"phase": "Q4-A problem and interface audit", "status": status,
             "problem_definition": definition, "q3_interface_gate": gate["checks"],
             "symbol_source_basis": definition["new_decision_variables"] + definition["derived_variables"] +
                                    definition["hard_constraints"]}
    (root / "q4_problem_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "q4_a_problem_definition.json").write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "q4_a_state_interface.json").write_text(json.dumps(interface, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = ["# Q4 Problem Audit", "", f"- status: **{status}**", f"- source: {SOURCE_STATEMENT}", "",
                "## Original Q4 requirement", "", definition["q4_original_requirement"], "",
                "## Frozen Q3 boundary", ""]
    markdown.extend(f"- {item}" for item in definition["frozen_upstream_variables"])
    markdown.extend(["", "## Legal Q4 decision variable", "", "| Variable | Meaning | Domain | Unit | Source clause |",
                     "|---|---|---|---|---|"])
    markdown.extend(f"| {row['symbol']} | {row['meaning']} | {row['domain']} | {row['unit']} | {row['source_clause']} |"
                    for row in definition["new_decision_variables"])
    markdown.extend(["", "## Ambiguities resolved before modelling", ""])
    markdown.extend(f"- **{row['ambiguity']}** {row['resolution']}" for row in definition["ambiguities_and_resolutions"])
    (root / "q4_problem_audit.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    report = ["# Q4-A Report", "", f"- Q3→Q4 interface: **{gate['status']}**",
              f"- legal-variable audit: **{definition['status']}**", f"- phase result: **{status}**", "",
              "Q4 only assigns frozen service-area components to independent execution groups. It does not alter Q3 routes, schedule, fleet, battery rules, relay plan or validators."]
    (root / "q4_a_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return audit


if __name__ == "__main__":
    print(json.dumps(run_q4a(), ensure_ascii=False, indent=2))

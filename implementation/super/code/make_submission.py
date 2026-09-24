# -*- coding: utf-8 -*-
"""把四问的求解结果整理成竞赛要求的结果提交表。

以官方《结果提交模板.xlsx》的六个工作表表头为准，逐列填入 results/ 下
由求解脚本直接产出的结果文件，不做任何人工改写或数值润色。

    Q1_单点组批   <- results/q1_batching_trips.csv（按 5.2.2 节推荐方案筛选）
    Q2_运输架次   <- results/q2_transport_trips.csv
    Q2_逐箱交付   <- results/q2_box_delivery.csv
    Q3_中继架次   <- results/q3_relay_trips.csv
    Q3_通信保障   <- results/q3_comm_support.csv
    Q4_分区配置   <- results/q4_config.csv

运行： .venv/Scripts/python.exe code/make_submission.py
输出： 结果提交.xlsx
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
REPO_ROOT = ROOT.parents[1]
TPL = REPO_ROOT / "results" / "submission" / "结果提交模板.xlsx"
OUT = ROOT / "结果提交.xlsx"

SHEETS = ["Q1_单点组批", "Q2_运输架次", "Q2_逐箱交付",
          "Q3_中继架次", "Q3_通信保障", "Q4_分区配置"]


def header_of(path, sheet):
    d = pd.read_excel(path, sheet_name=sheet, header=None)
    return [str(v).strip() for v in d.iloc[0].tolist()]


def q1_table():
    """问题一推荐方案：按 q1_best_per_sid.csv 指定的机型筛选架次。"""
    trips = pd.read_csv(RES / "q1_batching_trips.csv")
    best = pd.read_csv(RES / "q1_best_per_sid.csv")
    pick = {(r.sid, r.gtype): int(r.n_trips) for r in best.itertuples()}
    keep = [((r.sid, r.gtype) in pick) for r in trips.itertuples()]
    sel = trips[keep].copy()
    # 核对每个服务区的架次数与机型选择一致
    cnt = sel.groupby(["sid", "gtype"]).size().to_dict()
    for key, n in pick.items():
        assert cnt.get(key, 0) == n, "问题一架次数与推荐方案不符：%s" % (key,)
    sel = sel.sort_values(["sid", "gtype", "trip_id"])
    return pd.DataFrame({
        "架次编号": sel["trip_id"],
        "服务区编号": sel["sid"],
        "机型编号": sel["gtype"],
        "货箱编号列表": sel["boxes"].str.replace("|", "、", regex=False),
        "总质量（kg）": sel["mass"],
        "总体积（m³）": sel["vol"],
        "往返时间（s）": sel["rt_time"].round(1),
        "架次能耗（kWh）": sel["energy"].round(4),
        "返航SOC（%）": sel["soc_end"].round(2),
    })


def q2_trips_table():
    d = pd.read_csv(RES / "q2_transport_trips.csv")
    d = d.sort_values("start").reset_index(drop=True)
    return pd.DataFrame({
        "架次编号": d["trip_id"],
        "无人机编号": d["drone"],
        "机型编号": d["gtype"],
        "电池编号": d["battery"],
        "开始时刻（s）": d["start"].round(1),
        "访问服务区顺序": d["stops"].str.replace("->", "→", regex=False),
        "返回O01时刻（s）": d["end"].round(1),
        "架次能耗（kWh）": d["energy"].round(4),
    })


def q2_boxes_table():
    d = pd.read_csv(RES / "q2_box_delivery.csv")
    d = d.sort_values("deliver").reset_index(drop=True)
    return pd.DataFrame({
        "货箱编号": d["box"],
        "架次编号": d["trip_id"],
        "服务区编号": d["sid"],
        "交付完成时刻（s）": d["deliver"].round(1),
    })


def generic_table(csv, mapping, sort_by=None, ndigits=4):
    d = pd.read_csv(RES / csv)
    if sort_by:
        d = d.sort_values(sort_by).reset_index(drop=True)
    out = {}
    for k, v in mapping.items():
        if isinstance(v, tuple):
            col, nd = v
            out[k] = d[col].round(nd) if nd else d[col]
        else:
            out[k] = d[v]
    return pd.DataFrame(out)


def main():
    if not TPL.exists():
        sys.exit("找不到模板：%s" % TPL)
    print("模板：%s" % TPL)

    tables = {}
    tables["Q1_单点组批"] = q1_table()
    tables["Q2_运输架次"] = q2_trips_table()
    tables["Q2_逐箱交付"] = q2_boxes_table()
    tables["Q3_中继架次"] = generic_table(
        "q3_relay_trips.csv", {c: c for c in pd.read_csv(
            RES / "q3_relay_trips.csv").columns},
        sort_by="开始时刻（s）")
    tables["Q3_通信保障"] = generic_table(
        "q3_comm_support.csv", {c: c for c in pd.read_csv(
            RES / "q3_comm_support.csv").columns},
        sort_by=["运输架次编号", "开始时刻（s）"])
    q4 = pd.read_csv(RES / "q4_config.csv")
    q4 = q4[q4["K（2或3）"] == 2].reset_index(drop=True)   # 正文推荐 K=2
    tables["Q4_分区配置"] = q4

    with pd.ExcelWriter(OUT, engine="openpyxl") as w:
        for s in SHEETS:
            hdr = header_of(TPL, s)
            t = tables[s]
            assert list(t.columns) == hdr, \
                "表 %s 列名不符：\n  模板 %s\n  实际 %s" % (s, hdr, list(t.columns))
            t.to_excel(w, sheet_name=s, index=False)
            # 列宽自适应
            ws = w.sheets[s]
            for i, c in enumerate(t.columns, start=1):
                width = max(len(str(c)) * 2 + 4,
                            *(len(str(v)) + 2 for v in t[c].astype(str)))
                ws.column_dimensions[
                    ws.cell(row=1, column=i).column_letter].width = min(width, 46)
            print("  %-10s %3d 行 x %2d 列  -> %s"
                  % (s, len(t), len(t.columns), hdr[0] + " ..."))

    print("\n已写出：%s" % OUT)


if __name__ == "__main__":
    main()

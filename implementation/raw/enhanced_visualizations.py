# -*- coding: utf-8 -*-
"""p1-p4 统一增强可视化。

只读取各问已经生成的 CSV 和基础地理数据，输出文件名前缀为 enh_，
不覆盖原有 figures。图表分别覆盖路线、调度时序、资源占用、通信保障
和任务分区等关键结果。
"""
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from q00 import load_nodes, style_ax, CAT, DRONE_COLOR, INK, MUTED, SURFACE

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def save(fig, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path, bbox_inches="tight", facecolor=SURFACE, dpi=200)
    plt.close(fig)
    print("[增强图]", path)


def node_xy():
    o01, services = load_nodes()
    xy = {"O01": (float(o01["经度"]), float(o01["纬度"]))}
    for _, s in services.iterrows(): xy[str(s["服务区编号"])] = (float(s["经度"]), float(s["纬度"]))
    return o01, services, xy


def draw_route_map(routes, out, title, relay_points=None, group_of=None):
    o01, services, xy = node_xy()
    fig, ax = plt.subplots(figsize=(10, 7.2))
    ax.scatter([o01["经度"]], [o01["纬度"]], marker="s", s=170, color=INK, zorder=6, label="O01/G01")
    if group_of is None:
        ax.scatter(services["经度"], services["纬度"], s=52, color=MUTED, edgecolor=INK, linewidth=.5, label="服务区", zorder=4)
    else:
        for _, s in services.iterrows():
            g = group_of.get(str(s["服务区编号"]), 0)
            ax.scatter([s["经度"]], [s["纬度"]], s=70, color=CAT[g % len(CAT)], edgecolor=INK, zorder=4)
        ax.legend(handles=[Patch(color=CAT[g % len(CAT)], label=f"任务组{g+1}") for g in sorted(set(group_of.values()))], frameon=False, fontsize=8)
    seen = set()
    for r in routes:
        seq = r["停靠序列"] if "停靠序列" in r else r.get("path", "O01->O01")
        path = [x for x in str(seq).split("->") if x in xy]
        if len(path) < 2: continue
        typ = str(r.get("机型编号", r.get("type", "")))
        xs = [xy[p][0] for p in path]; ys = [xy[p][1] for p in path]
        label = f"{typ}型路线" if typ not in seen else None; seen.add(typ)
        ax.plot(xs, ys, color=DRONE_COLOR.get(typ, CAT[0]), lw=1.2, alpha=.48, label=label, zorder=2)
        # 访问顺序箭头
        for i in range(len(xs)-1):
            ax.annotate("", xy=(xs[i+1], ys[i+1]), xytext=(xs[i], ys[i]), arrowprops=dict(arrowstyle="->", color=DRONE_COLOR.get(typ, CAT[0]), alpha=.35, lw=.7))
    for _, s in services.iterrows(): ax.annotate(str(s["服务区编号"]), (s["经度"], s["纬度"]), xytext=(3,3), textcoords="offset points", fontsize=7)
    if relay_points:
        for j, p in enumerate(relay_points):
            ax.scatter([p[0]], [p[1]], marker="^", s=100, color=CAT[3], edgecolor=INK, zorder=7, label="中继悬停点" if j == 0 else None)
    style_ax(ax, "both"); ax.set_xlabel("经度"); ax.set_ylabel("纬度"); ax.set_title(title, loc="left", fontsize=13, fontweight="bold"); ax.legend(frameon=False, fontsize=8, loc="best")
    save(fig, out)


def draw_batch_time(df, out, title, id_col, type_col, time_col, start_col=None, end_col=None):
    d = df.copy().reset_index(drop=True)
    if start_col and end_col:
        st = pd.to_numeric(d[start_col]); en = pd.to_numeric(d[end_col])
    else:
        dur = pd.to_numeric(d[time_col]).fillna(0.0)
        st = dur.cumsum() - dur
        en = st + dur
    fig, ax = plt.subplots(figsize=(12, max(5, .20*len(d)+2)))
    labels = d[id_col].astype(str).tolist()
    for i, (_, r) in enumerate(d.iterrows()):
        typ = str(r[type_col]) if type_col in d else ""
        ax.barh(i, float(en.iloc[i]-st.iloc[i])/3600, left=float(st.iloc[i])/3600, height=.62, color=DRONE_COLOR.get(typ, CAT[i % 5]), alpha=.85)
        ax.text(float(en.iloc[i])/3600, i, f" {typ}", va="center", fontsize=7)
    ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels, fontsize=7); ax.invert_yaxis(); ax.set_xlabel("时间 (h)"); ax.set_title(title, loc="left", fontsize=13, fontweight="bold"); style_ax(ax,"x")
    save(fig, out)


def draw_resource_timeline(events, out, title):
    if events.empty: return
    e = events.copy(); e["资源编号"] = e["资源编号"].astype(str)
    resources = list(dict.fromkeys(e["资源编号"].tolist())); y = {x:i for i,x in enumerate(resources)}
    colors = {"飞行":CAT[0], "运输架次":CAT[0], "充电":CAT[3], "中继飞行与服务":CAT[3], "电池充电":CAT[3]}
    fig, ax = plt.subplots(figsize=(13, max(5, .26*len(resources)+2)))
    seen=set()
    for _, r in e.iterrows():
        kind = str(r.get("事件类型", r.get("活动", "活动"))); c=colors.get(kind,CAT[1]); label=kind if kind not in seen else None; seen.add(kind)
        a=float(r.get("开始_s",r.get("start",0))); b=float(r.get("结束_s",r.get("end",0)))
        ax.barh(y[r["资源编号"]], max(0,b-a)/3600, left=a/3600, height=.65, color=c, label=label)
    ax.set_yticks(range(len(resources))); ax.set_yticklabels(resources, fontsize=7); ax.set_xlabel("时间 (h)"); ax.set_title(title, loc="left", fontsize=13, fontweight="bold"); style_ax(ax,"x"); ax.legend(frameon=False, fontsize=8)
    save(fig,out)


def draw_area_load(df, out, title, area_col="服务区编号", count_col=None, energy_col=None):
    d=df.copy(); area=d[area_col].astype(str)
    grp=d.groupby(area).size().rename("架次")
    if count_col and count_col in d:
        boxes=d.groupby(area)[count_col].sum().rename("箱数"); g=pd.concat([grp,boxes],axis=1).fillna(0)
    else: g=grp.to_frame()
    fig, ax=plt.subplots(figsize=(11,5)); x=np.arange(len(g)); width=.35
    ax.bar(x-width/2,g["架次"],width,label="架次",color=CAT[0])
    if "箱数" in g: ax.bar(x+width/2,g["箱数"],width,label="货箱数",color=CAT[2])
    ax.set_xticks(x,g.index,rotation=35); ax.set_ylabel("数量"); ax.set_title(title,loc="left",fontsize=13,fontweight="bold"); style_ax(ax,"y"); ax.legend(frameon=False)
    save(fig,out)


def draw_scope_note(out, title, text):
    fig, ax = plt.subplots(figsize=(9, 3.2)); ax.axis("off")
    ax.text(.5, .58, title, ha="center", va="center", fontsize=15, fontweight="bold", color=INK)
    ax.text(.5, .35, text, ha="center", va="center", fontsize=12, color=MUTED,
            bbox=dict(boxstyle="round,pad=.8", facecolor="#f4f1e9", edgecolor="#c3c2b7"))
    save(fig, out)


def p1_viz(tag, folder, batch_file, batch_mode="p1"):
    b=pd.read_csv(batch_file,encoding="utf-8-sig")
    routes=[]
    for _,r in b.iterrows(): routes.append({"停靠序列":f"O01->{r['服务区编号']}->O01","机型编号":r.get("机型编号","")})
    draw_route_map(routes,os.path.join(folder,"enh_01_运输路线地图.png"),f"{tag} 运输路线与服务区覆盖")
    draw_batch_time(b,os.path.join(folder,"enh_02_批次调度时序.png"),f"{tag} 组批任务时序", "批次编号", "机型编号", "累计作业时间_s" if "累计作业时间_s" in b else "T_batch_s")
    # 资源占用：按机型的批次数、总能耗和质量
    typ=b.groupby("机型编号").agg(架次=("批次编号","count"),总能耗_kWh=("往返能耗_kWh" if "往返能耗_kWh" in b else "E_batch_kWh","sum"),总质量_kg=("总质量_kg","sum")).reset_index()
    fig,ax=plt.subplots(figsize=(9,5)); x=np.arange(len(typ)); w=.26
    ax.bar(x-w,typ["架次"],w,label="架次",color=CAT[0]); ax.bar(x,typ["总能耗_kWh"],w,label="能耗(kWh)",color=CAT[1]); ax.bar(x+w,typ["总质量_kg"]/10,w,label="质量/10",color=CAT[2]); ax.set_xticks(x,typ["机型编号"]); ax.set_title(f"{tag} 机型资源占用与负载",loc="left",fontweight="bold"); style_ax(ax,"y"); ax.legend(frameon=False); save(fig,os.path.join(folder,"enh_03_资源占用.png"))
    draw_area_load(b,os.path.join(folder,"enh_04_服务区任务分布.png"),f"{tag} 服务区组批与任务分布","服务区编号","箱数")
    draw_scope_note(os.path.join(folder,"enh_05_通信约束范围.png"),f"{tag} 通信约束范围","本问题不将通信保障作为优化约束；通信状态由问题三单独建模并校验。")


def p2_viz(tag, folder):
    out=os.path.join(ROOT,folder,"outputs"); figdir=os.path.join(ROOT,folder,"figures")
    r=pd.read_csv(os.path.join(out,f"{tag}_routes.csv"),encoding="utf-8-sig"); s=pd.read_csv(os.path.join(out,f"{tag}_sorties.csv"),encoding="utf-8-sig"); tl=pd.read_csv(os.path.join(out,f"{tag}_resource_timeline.csv"),encoding="utf-8-sig")
    draw_route_map(r.to_dict("records"),os.path.join(figdir,"enh_01_运输路线地图.png"),f"{tag} 多点运输路线与访问顺序")
    draw_batch_time(s,os.path.join(figdir,"enh_02_运输调度时序.png"),f"{tag} 运输无人机架次调度时序","架次编号","机型编号","返航时刻_s","起飞时刻_s","返航时刻_s")
    draw_resource_timeline(tl,os.path.join(figdir,"enh_03_运输电池资源占用.png"),f"{tag} 无人机与共享电池资源占用")
    draw_area_load(r.assign(**{"服务区编号":r["停靠序列"].str.extract(r"(S\d+)",expand=False)}),os.path.join(figdir,"enh_04_路线任务分区.png"),f"{tag} 服务区任务覆盖","服务区编号","箱数")
    draw_scope_note(os.path.join(figdir,"enh_05_通信约束范围.png"),f"{tag} 通信约束范围","本问题不考虑通信保障；通信链路和中继资源在问题三中加入联合调度。")


def p3_viz(tag, folder):
    out=os.path.join(ROOT,folder,"outputs"); figdir=os.path.join(ROOT,folder,"figures")
    r=pd.read_csv(os.path.join(out,f"{tag}_routes.csv"),encoding="utf-8-sig"); rs=pd.read_csv(os.path.join(out,f"{tag}_relay_schedule.csv"),encoding="utf-8-sig"); cs=pd.read_csv(os.path.join(out,f"{tag}_communication_states.csv"),encoding="utf-8-sig"); tl=pd.read_csv(os.path.join(out,f"{tag}_resource_timeline.csv"),encoding="utf-8-sig")
    relay_points=[]
    lon_col = "中继经度" if "中继经度" in r.columns else ("经度" if "经度" in r.columns else None)
    lat_col = "中继纬度" if "中继纬度" in r.columns else ("纬度" if "纬度" in r.columns else None)
    if lon_col and lat_col:
        for _,x in r.drop_duplicates([lon_col,lat_col]).iterrows():
            if bool(x.get("是否需要中继", False)):
                relay_points.append((float(x[lon_col]),float(x[lat_col])))
    draw_route_map(r.to_dict("records"),os.path.join(figdir,"enh_01_运输路线与中继链路.png"),f"{tag} 运输路线—中继悬停点—G01",relay_points=relay_points)
    draw_batch_time(r,os.path.join(figdir,"enh_02_联合调度时序.png"),f"{tag} 运输架次联合调度时序","架次编号","机型编号","返航_s","起飞_s","返航_s")
    draw_resource_timeline(tl,os.path.join(figdir,"enh_03_运输中继资源占用.png"),f"{tag} 运输/中继无人机与能源组件占用")
    # 通信状态热图：直连、中继、中断三类
    order=list(r["路线编号"]); cmap={"直连":CAT[2],"中继":CAT[3],"中断":"#d94b4b"}; fig,ax=plt.subplots(figsize=(13,max(5,.22*len(order)+2)))
    for i,rid in enumerate(order):
        q=cs[cs["路线编号"]==rid].sort_values("采样点序号"); n=max(1,len(q));
        for j,(_,x) in enumerate(q.iterrows()): ax.barh(i,1/n,left=j/n,color=cmap.get(x["通信状态"],MUTED),height=.72)
    ax.set_yticks(range(len(order)),order,fontsize=7); ax.set_xlabel("架次内相对时间比例"); ax.set_title(f"{tag} 连续通信保障状态",loc="left",fontweight="bold"); style_ax(ax,"x"); ax.legend(handles=[Patch(color=cmap[k],label=k) for k in cmap],frameon=False,ncol=3); save(fig,os.path.join(figdir,"enh_04_通信保障状态.png"))


def p4_viz(tag, folder):
    out=os.path.join(ROOT,folder,"outputs"); figdir=os.path.join(ROOT,folder,"figures")
    r=pd.read_csv(os.path.join(ROOT,"p3-1","outputs","p3-1_routes.csv"),encoding="utf-8-sig")
    # 以K=2分区绘制任务组路线图，并分别绘制2/3组资源与时序
    part2=pd.read_csv(os.path.join(out,f"{tag}_partition_K2.csv"),encoding="utf-8-sig")
    group_of={s:int(row["任务组"])-1 for _,row in part2.iterrows() for s in str(row["服务区列表"]).split("、")}
    draw_route_map(r.to_dict("records"),os.path.join(figdir,"enh_01_任务分区与运输路线.png"),f"{tag} 任务分区约束下运输路线",group_of=group_of)
    # 由任务组分区和路线首个服务区连接路线与组别
    rr=r.copy(); rr["任务组"]=rr["停靠序列"].str.extract(r"(S\d+)",expand=False).map(group_of).fillna(0).astype(int)+1
    draw_batch_time(rr,os.path.join(figdir,"enh_02_分区调度时序.png"),f"{tag} 任务组调度时序","架次编号","任务组","返航_s","起飞_s","返航_s")
    for k in (2,3):
        res=pd.read_csv(os.path.join(out,f"{tag}_resources_K{k}.csv"),encoding="utf-8-sig")
        fig,ax=plt.subplots(figsize=(11,5)); pivot=res.pivot(index="资源",columns="任务组",values="需求数量").fillna(0); inv=res.drop_duplicates("资源").set_index("资源")["现有库存"].reindex(pivot.index).fillna(0); x=np.arange(len(pivot)); w=.8/k
        for j,col in enumerate(pivot.columns): ax.bar(x+(j-(k-1)/2)*w,pivot[col],w,label=f"组{col}",color=CAT[j])
        ax.plot(x,inv,"k--o",label="现有库存"); ax.set_xticks(x,pivot.index,rotation=35,ha="right",fontsize=8); ax.set_ylabel("数量"); ax.set_title(f"{tag} {k}组资源独立配置",loc="left",fontweight="bold"); style_ax(ax,"y"); ax.legend(frameon=False); save(fig,os.path.join(figdir,f"enh_0{3 if k==2 else 5}_{k}组资源配置.png"))
    wl=pd.read_csv(os.path.join(out,f"{tag}_workload_K2.csv"),encoding="utf-8-sig"); fig,ax=plt.subplots(figsize=(9,4.5)); ax.bar(wl["任务组"].astype(str),wl["作业时长_s"]/3600,color=CAT[:len(wl)]); ax.set_xlabel("任务组"); ax.set_ylabel("作业时长 (h)"); ax.set_title(f"{tag} 任务组工作量与调度负荷",loc="left",fontweight="bold"); style_ax(ax,"y"); save(fig,os.path.join(figdir,"enh_04_任务分区工作量.png"))
    # 问题四保持问题三的通信保障关系不变，按任务组汇总直连/中继/中断状态。
    cs_path=os.path.join(ROOT,"p3-1","outputs","p3-1_communication_states.csv")
    if os.path.exists(cs_path):
        cs=pd.read_csv(cs_path,encoding="utf-8-sig"); route_group={}
        for _,x in r.iterrows():
            area=str(x["停靠序列"]).split("->")[1] if "->" in str(x["停靠序列"]) else ""
            route_group[str(x["路线编号"])] = int(group_of.get(area,0))+1
        cs["任务组"]=cs["路线编号"].map(route_group).fillna(1).astype(int); tab=cs.groupby(["任务组","通信状态"]).size().unstack(fill_value=0)
        fig,ax=plt.subplots(figsize=(9,4.5)); x=np.arange(len(tab)); bottom=np.zeros(len(tab)); cmap={"直连":CAT[2],"中继":CAT[3],"中断":"#d94b4b"}
        for state in ["直连","中继","中断"]:
            if state in tab: ax.bar(x,tab[state],bottom=bottom,color=cmap[state],label=state); bottom+=tab[state].to_numpy()
        ax.set_xticks(x,[f"组{int(i)}" for i in tab.index]); ax.set_ylabel("通信采样点数"); ax.set_title(f"{tag} 分区后继承的问题三通信保障",loc="left",fontweight="bold"); style_ax(ax,"y"); ax.legend(frameon=False); save(fig,os.path.join(figdir,"enh_06_通信保障继承.png"))


def main():
    # 问题一：分别使用两套组批结果
    p1base=os.path.join(ROOT,"p1-1","outputs","p1-1_第1小问_基准组批.csv")
    p1cheb=os.path.join(ROOT,"p1-2","outputs","p1-2_最终Chebyshev组批方案.csv")
    p1_viz("p1-1",os.path.join(ROOT,"p1-1","figures"),p1base)
    p1_viz("p1-2",os.path.join(ROOT,"p1-2","figures"),p1cheb)
    p2_viz("p2-1", "p2-1"); p2_viz("p2-2", "p2-2")
    p3_viz("p3-1", "p3-1"); p3_viz("p3-2", "p3-2")
    p4_viz("p4-1", "p4-1"); p4_viz("p4-2", "p4-2")


if __name__ == "__main__": main()

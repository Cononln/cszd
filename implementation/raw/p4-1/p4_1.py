# -*- coding: utf-8 -*-
"""问题四方法1：冲突图连通分量 + 完全枚举精确分区。"""
import os, sys
import pandas as pd
import numpy as np

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,ROOT)
from q00 import load_nodes, load_transport_drone, load_relay_drone
from p4_common import (load_fixed_plan, build_components, all_partitions, normalize_label,
                       evaluate_partition, partition_rows, resource_rows, workload_rows,
                       save_figures)

OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"outputs"); FIG=os.path.join(os.path.dirname(os.path.abspath(__file__)),"figures")
os.makedirs(OUT,exist_ok=True); os.makedirs(FIG,exist_ok=True)

def write_solution(tag, plan, k, components):
    pd.DataFrame(partition_rows(plan,components,k)).to_csv(os.path.join(OUT,f"{tag}_partition_K{k}.csv"),index=False,encoding="utf-8-sig")
    pd.DataFrame(resource_rows(plan,k)).to_csv(os.path.join(OUT,f"{tag}_resources_K{k}.csv"),index=False,encoding="utf-8-sig")
    pd.DataFrame(workload_rows(plan)).to_csv(os.path.join(OUT,f"{tag}_workload_K{k}.csv"),index=False,encoding="utf-8-sig")

def main():
    routes=load_fixed_plan("p3-1"); o01,services=load_nodes(); components,comp_of=build_components(routes,services)
    tspec,tfleet,tbatt=load_transport_drone(); rspec_df,rfleet,rstock=load_relay_drone(); rspec=rspec_df.iloc[0]; rstock_row=rstock.iloc[0]
    best_plans={}; records=[]
    for k in (2,3):
        best=None; count=0
        for a in all_partitions(len(components),k):
            count+=1
            p=evaluate_partition(routes,a,k,tspec,tfleet,tbatt,rspec,rfleet,rstock_row,components)
            records.append({"方法":"精确枚举","任务组数":k,"分区编码":"-".join(map(str,a)),"资源缺口":p["gap"],"总资源需求":p["total_need"],"均衡系数":p["balance"],"资源冗余":p["redundancy"]})
            if best is None or p["score"]<best["score"]: best=p
        best_plans[k]=best; write_solution("p4-1",best,k,components)
        print(f"K={k}: 枚举 {count} 个分区，最优 score={best['score']}")
    rec=pd.DataFrame(records); rec.to_csv(os.path.join(OUT,"p4-1_all_partitions.csv"),index=False,encoding="utf-8-sig")
    # 取每个K的非支配解，用于比较资源规模与均衡性
    pf=[]
    for k in (2,3):
        sub=rec[rec["任务组数"]==k].copy()
        vals=sub[["资源缺口","总资源需求","均衡系数","资源冗余"]].to_numpy()
        keep=[]
        for i,v in enumerate(vals):
            if not any(np.all(w<=v+1e-12) and np.any(w<v-1e-12) for j,w in enumerate(vals) if j!=i): keep.append(i)
        pf.append(sub.iloc[keep])
    pd.concat(pf,ignore_index=True).to_csv(os.path.join(OUT,"p4-1_pareto_front.csv"),index=False,encoding="utf-8-sig")
    comp=[]
    for k,p in best_plans.items():
        comp.append({"任务组数":k,"资源缺口":p["gap"],"总资源需求":p["total_need"],"均衡系数":p["balance"],"资源冗余":p["redundancy"],"服务区数":len(services),"不可拆分任务块数":len(components)})
    pd.DataFrame(comp).to_csv(os.path.join(OUT,"p4-1_comparison.csv"),index=False,encoding="utf-8-sig")
    summary=["问题四 p4-1：冲突图+完全枚举精确分区",f"服务区数：{len(services)}；不可拆分任务块数：{len(components)}","分区目标：先最小资源缺口，再最小资源需求、工作量不均衡和冗余。"]
    for k,p in best_plans.items(): summary += [f"{k}组：资源缺口={p['gap']}，总资源需求={p['total_need']}，均衡系数={p['balance']:.4f}，冗余={p['redundancy']}"]
    with open(os.path.join(OUT,"p4-1_summary.txt"),"w",encoding="utf-8") as f:f.write("\n".join(summary))
    save_figures(FIG,"p4-1",routes,services,best_plans,components)
    print("\n".join(summary))

if __name__=="__main__":main()

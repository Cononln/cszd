# -*- coding: utf-8 -*-
"""问题四增强方案1：通信风险感知的精确任务分区。"""
import os,sys
import numpy as np
import pandas as pd
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,ROOT)
from q00 import load_nodes,load_transport_drone,load_relay_drone
from p4_common import (load_fixed_plan,build_components,all_partitions,evaluate_partition,
                       partition_rows,resource_rows,workload_rows,save_figures)

OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"outputs"); FIG=os.path.join(os.path.dirname(os.path.abspath(__file__)),"figures")
os.makedirs(OUT,exist_ok=True); os.makedirs(FIG,exist_ok=True)

def main():
    routes=load_fixed_plan("p3-3pro"); o01,services=load_nodes(); components,comp_of=build_components(routes,services)
    tspec,tfleet,tbatt=load_transport_drone(); rspec_df,rfleet,rstock=load_relay_drone(); rspec=rspec_df.iloc[0]; rstock_row=rstock.iloc[0]
    cs=pd.read_csv(os.path.join(ROOT,"p3-3pro","outputs","p3-3pro_communication_states.csv"),encoding="utf-8-sig")
    route_risk=cs.assign(is_relay=(cs["通信状态"]=="中继").astype(int),is_interrupt=(cs["通信状态"]=="中断").astype(int)).groupby("路线编号").agg(relay_ratio=("is_relay","mean"),interrupt=("is_interrupt","sum")).to_dict("index")
    for r in routes: r["comm_risk"]=route_risk.get(r["route_id"],{"relay_ratio":0.0,"interrupt":0})["relay_ratio"]
    best_plans={}; allrows=[]
    for k in (2,3):
        best=None
        for a in all_partitions(len(components),k):
            p=evaluate_partition(routes,a,k,tspec,tfleet,tbatt,rspec,rfleet,rstock_row,components)
            risks=[sum(r["comm_risk"] for r in routes if p["group_of"][r["component"]]==g) for g in range(k)]
            risk_balance=float(np.std(risks)/(np.mean(risks)+1e-9)) if risks else 0.0
            p["risk_balance"]=risk_balance; p["score_pro"]=(p["gap"],p["total_need"],risk_balance,p["balance"],p["redundancy"])
            allrows.append({"任务组数":k,"分区编码":"-".join(map(str,a)),"资源缺口":p["gap"],"总资源需求":p["total_need"],"通信风险均衡系数":risk_balance,"工作量均衡系数":p["balance"],"资源冗余":p["redundancy"]})
            if best is None or p["score_pro"]<best["score_pro"]: best=p
        best_plans[k]=best
        pd.DataFrame(partition_rows(best,components,k)).to_csv(os.path.join(OUT,f"p4-3pro_partition_K{k}.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(resource_rows(best,k)).to_csv(os.path.join(OUT,f"p4-3pro_resources_K{k}.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(workload_rows(best)).to_csv(os.path.join(OUT,f"p4-3pro_workload_K{k}.csv"),index=False,encoding="utf-8-sig")
    pd.DataFrame(allrows).to_csv(os.path.join(OUT,"p4-3pro_all_partitions.csv"),index=False,encoding="utf-8-sig")
    pd.DataFrame([{ "任务组数":k,"资源缺口":p["gap"],"总资源需求":p["total_need"],"通信风险均衡系数":p["risk_balance"],"工作量均衡系数":p["balance"],"资源冗余":p["redundancy"]} for k,p in best_plans.items()]).to_csv(os.path.join(OUT,"p4-3pro_comparison.csv"),index=False,encoding="utf-8-sig")
    summary=["问题四 p4-3pro：通信风险感知的精确任务分区",f"服务区数：{len(services)}；不可拆分任务块数：{len(components)}","目标优先级：资源缺口→资源总需求→通信风险均衡→工作量均衡→冗余。"]
    for k,p in best_plans.items(): summary.append(f"{k}组：缺口={p['gap']}，总资源需求={p['total_need']}，通信风险均衡={p['risk_balance']:.4f}，工作量均衡={p['balance']:.4f}")
    with open(os.path.join(OUT,"p4-3pro_summary.txt"),"w",encoding="utf-8") as f:f.write("\n".join(summary))
    save_figures(FIG,"p4-3pro",routes,services,best_plans,components); print("\n".join(summary))

if __name__=="__main__":main()

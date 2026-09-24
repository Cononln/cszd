# -*- coding: utf-8 -*-
"""问题四增强方案2：通信风险—资源冗余联合局部搜索分区。"""
import os,sys,random,math
import numpy as np
import pandas as pd
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,ROOT)
from q00 import load_nodes,load_transport_drone,load_relay_drone
from p4_common import (load_fixed_plan,build_components,evaluate_partition,partition_rows,resource_rows,workload_rows,save_figures)

OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"outputs"); FIG=os.path.join(os.path.dirname(os.path.abspath(__file__)),"figures")
os.makedirs(OUT,exist_ok=True); os.makedirs(FIG,exist_ok=True); SEED=20260923

def evaluate_pro(routes,a,k,tspec,tfleet,tbatt,rspec,rfleet,rstock,components,risk):
    p=evaluate_partition(routes,a,k,tspec,tfleet,tbatt,rspec,rfleet,rstock,components)
    risks=[sum(risk.get(r["route_id"],0.0) for r in routes if p["group_of"][r["component"]]==g) for g in range(k)]
    p["risk_balance"]=float(np.std(risks)/(np.mean(risks)+1e-9)) if risks else 0.0
    p["score_pro"]=1e6*p["gap"]+100*p["total_need"]+2e4*p["risk_balance"]+1e4*p["balance"]+p["redundancy"]
    return p

def main():
    rng=random.Random(SEED); routes=load_fixed_plan("p3-4pro"); o01,services=load_nodes(); components,comp_of=build_components(routes,services)
    tspec,tfleet,tbatt=load_transport_drone(); rspec_df,rfleet,rstock=load_relay_drone(); rspec=rspec_df.iloc[0]; rstock_row=rstock.iloc[0]
    cs=pd.read_csv(os.path.join(ROOT,"p3-4pro","outputs","p3-4pro_communication_states.csv"),encoding="utf-8-sig")
    risk=cs.assign(v=(cs["通信状态"]=="中继").astype(int)).groupby("路线编号")["v"].mean().to_dict()
    plans={}; history=[]
    for k in (2,3):
        # 轮流按任务块权重初始化，确保各组非空
        a=[i%k for i in range(len(components))]; cur=evaluate_pro(routes,tuple(a),k,tspec,tfleet,tbatt,rspec,rfleet,rstock_row,components,risk); best=cur; best_a=tuple(a)
        for it in range(1,251):
            cand=list(a)
            if rng.random()<.75:
                i=rng.randrange(len(cand)); new=rng.randrange(k)
                if cand.count(cand[i])<=1 or new==cand[i]: continue
                cand[i]=new
            else:
                i,j=rng.sample(range(len(cand)),2); cand[i],cand[j]=cand[j],cand[i]
            cp=evaluate_pro(routes,tuple(cand),k,tspec,tfleet,tbatt,rspec,rfleet,rstock_row,components,risk)
            delta=cp["score_pro"]-cur["score_pro"]; temp=max(.01,1.8*(1-it/250))
            if delta<=0 or rng.random()<math.exp(-delta/(temp*1000)): a=list(cand); cur=cp
            if cur["score_pro"]<best["score_pro"]: best=cur; best_a=tuple(a)
            history.append({"任务组数":k,"迭代":it,"目标值":cur["score_pro"],"资源缺口":cur["gap"],"总资源需求":cur["total_need"],"通信风险均衡系数":cur["risk_balance"],"工作量均衡系数":cur["balance"]})
        best["assignment"]=best_a; plans[k]=best
        pd.DataFrame(partition_rows(best,components,k)).to_csv(os.path.join(OUT,f"p4-4pro_partition_K{k}.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(resource_rows(best,k)).to_csv(os.path.join(OUT,f"p4-4pro_resources_K{k}.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(workload_rows(best)).to_csv(os.path.join(OUT,f"p4-4pro_workload_K{k}.csv"),index=False,encoding="utf-8-sig")
    h=pd.DataFrame(history); h.to_csv(os.path.join(OUT,"p4-4pro_search_history.csv"),index=False,encoding="utf-8-sig")
    pd.DataFrame([{ "任务组数":k,"资源缺口":p["gap"],"总资源需求":p["total_need"],"通信风险均衡系数":p["risk_balance"],"工作量均衡系数":p["balance"],"资源冗余":p["redundancy"]} for k,p in plans.items()]).to_csv(os.path.join(OUT,"p4-4pro_comparison.csv"),index=False,encoding="utf-8-sig")
    summary=["问题四 p4-4pro：通信风险—资源冗余联合局部搜索",f"服务区数：{len(services)}；不可拆分任务块数：{len(components)}","邻域：任务块移动与交换；目标同时考虑资源缺口、总需求、通信风险均衡、工作量均衡和冗余。"]
    for k,p in plans.items(): summary.append(f"{k}组：缺口={p['gap']}，总资源需求={p['total_need']}，通信风险均衡={p['risk_balance']:.4f}，工作量均衡={p['balance']:.4f}")
    with open(os.path.join(OUT,"p4-4pro_summary.txt"),"w",encoding="utf-8") as f:f.write("\n".join(summary))
    save_figures(FIG,"p4-4pro",routes,services,plans,components); import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(9,4.5));
    for k in (2,3):
        z=h[h["任务组数"]==k]; ax.plot(z["迭代"],z["目标值"],label=f"{k}组")
    ax.set_xlabel("迭代"); ax.set_ylabel("鲁棒分区目标值"); ax.set_title("p4-4pro 局部搜索收敛",loc="left",fontweight="bold"); from q00 import style_ax; style_ax(ax,"y"); ax.legend(frameon=False); fig.savefig(os.path.join(FIG,"p4-4pro_05_搜索收敛.png"),bbox_inches="tight",dpi=180); plt.close(fig); print("\n".join(summary))

if __name__=="__main__":main()

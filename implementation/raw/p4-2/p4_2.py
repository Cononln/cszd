# -*- coding: utf-8 -*-
"""问题四方法2：负载均衡初始化 + 任务块移动/交换局部搜索。"""
import os, sys, random, math
import pandas as pd
import numpy as np

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,ROOT)
from q00 import load_nodes, load_transport_drone, load_relay_drone
from p4_common import (load_fixed_plan, build_components, evaluate_partition,
                       partition_rows, resource_rows, workload_rows, save_figures)

OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"outputs"); FIG=os.path.join(os.path.dirname(os.path.abspath(__file__)),"figures")
os.makedirs(OUT,exist_ok=True); os.makedirs(FIG,exist_ok=True)
SEED=20260923

def scalar_score(p):
    # 资源缺口为硬优先级；其后兼顾总需求、负载均衡和冗余
    return 1e6*p["gap"]+100*p["total_need"]+1e4*p["balance"]+p["redundancy"]

def initial_assignment(routes,components,k):
    weights=[]
    for c in components:
        rs=[r for r in routes if r["component"]==components.index(c)]
        weights.append(sum(r["end"]-r["start"]+r["energy"]*100+r["box_count"]*20 for r in rs))
    order=sorted(range(len(components)),key=lambda i:weights[i],reverse=True)
    a=[None]*len(components); loads=[0.0]*k
    for i in order:
        g=int(np.argmin(loads)); a[i]=g; loads[g]+=weights[i]
    return tuple(a)

def local_search(routes,components,k,tspec,tfleet,tbatt,rspec,rfleet,rstock,rng):
    cur_a=initial_assignment(routes,components,k)
    cur=evaluate_partition(routes,cur_a,k,tspec,tfleet,tbatt,rspec,rfleet,rstock,components)
    best=cur; best_a=cur_a; hist=[]
    for it in range(1,301):
        cand=list(cur_a)
        if rng.random()<0.72:
            i=rng.randrange(len(cand)); old=cand[i]; new=rng.randrange(k)
            if new==old or cand.count(old)<=1: continue
            cand[i]=new
        else:
            i,j=rng.sample(range(len(cand)),2)
            if cand[i]==cand[j]: continue
            cand[i],cand[j]=cand[j],cand[i]
        cand_a=tuple(cand); cand_p=evaluate_partition(routes,cand_a,k,tspec,tfleet,tbatt,rspec,rfleet,rstock,components)
        delta=scalar_score(cand_p)-scalar_score(cur)
        temp=max(0.01,2.0*(1-it/300))
        if delta<=0 or rng.random()<math.exp(-delta/(temp*1000.0)):
            cur_a,cur=cand_a,cand_p
        if scalar_score(cur)<scalar_score(best): best,best_a=cur,cur_a
        hist.append({"迭代":it,"目标值":scalar_score(cur),"资源缺口":cur["gap"],"总资源需求":cur["total_need"],"均衡系数":cur["balance"],"资源冗余":cur["redundancy"]})
    best["assignment"]=best_a
    return best,hist

def main():
    rng=random.Random(SEED); routes=load_fixed_plan("p3-1"); o01,services=load_nodes(); components,comp_of=build_components(routes,services)
    tspec,tfleet,tbatt=load_transport_drone(); rspec_df,rfleet,rstock=load_relay_drone(); rspec=rspec_df.iloc[0]; rstock_row=rstock.iloc[0]
    plans={}; histories=[]
    for k in (2,3):
        p,h=local_search(routes,components,k,tspec,tfleet,tbatt,rspec,rfleet,rstock_row,rng); plans[k]=p
        for x in h: x["任务组数"]=k
        histories.extend(h)
        pd.DataFrame(partition_rows(p,components,k)).to_csv(os.path.join(OUT,f"p4-2_partition_K{k}.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(resource_rows(p,k)).to_csv(os.path.join(OUT,f"p4-2_resources_K{k}.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(workload_rows(p)).to_csv(os.path.join(OUT,f"p4-2_workload_K{k}.csv"),index=False,encoding="utf-8-sig")
    pd.DataFrame(histories).to_csv(os.path.join(OUT,"p4-2_search_history.csv"),index=False,encoding="utf-8-sig")
    comp=[]
    for k,p in plans.items(): comp.append({"任务组数":k,"资源缺口":p["gap"],"总资源需求":p["total_need"],"均衡系数":p["balance"],"资源冗余":p["redundancy"],"不可拆分任务块数":len(components)})
    pd.DataFrame(comp).to_csv(os.path.join(OUT,"p4-2_comparison.csv"),index=False,encoding="utf-8-sig")
    # 用局部搜索得到的两个代表解制作一个简洁的前沿表
    pd.DataFrame([{**{"任务组数":k},"资源缺口":p["gap"],"总资源需求":p["total_need"],"均衡系数":p["balance"],"资源冗余":p["redundancy"]} for k,p in plans.items()]).to_csv(os.path.join(OUT,"p4-2_pareto_front.csv"),index=False,encoding="utf-8-sig")
    summary=["问题四 p4-2：负载均衡初始化+局部搜索",f"服务区数：{len(services)}；不可拆分任务块数：{len(components)}","邻域：任务块移动与任务块交换；接受准则：资源缺口优先的模拟退火。"]
    for k,p in plans.items(): summary += [f"{k}组：资源缺口={p['gap']}，总资源需求={p['total_need']}，均衡系数={p['balance']:.4f}，冗余={p['redundancy']}"]
    with open(os.path.join(OUT,"p4-2_summary.txt"),"w",encoding="utf-8") as f:f.write("\n".join(summary))
    save_figures(FIG,"p4-2",routes,services,plans,components)
    # 搜索收敛可视化
    import matplotlib.pyplot as plt
    h=pd.DataFrame(histories); fig,ax=plt.subplots(figsize=(9,4.5))
    for k in (2,3):
        s=h[h["任务组数"]==k]; ax.plot(s["迭代"],s["目标值"],label=f"{k}组",lw=1.7)
    ax.set_xlabel("迭代"); ax.set_ylabel("加权目标值"); ax.set_title("p4-2 分区局部搜索收敛曲线",loc="left",fontweight="bold"); from q00 import style_ax; style_ax(ax,"y"); ax.legend(frameon=False); fig.savefig(os.path.join(FIG,"p4-2_05_搜索收敛.png"),bbox_inches="tight",dpi=180); plt.close(fig)
    print("\n".join(summary))

if __name__=="__main__":main()

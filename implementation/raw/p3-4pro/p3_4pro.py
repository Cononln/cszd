# -*- coding: utf-8 -*-
"""问题三增强方案2：链路损耗扰动与中继容量情景下的鲁棒联合调度。"""
import os,sys,copy
import pandas as pd
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,ROOT)
from p3pro_common import prepare_context,candidate_pool,write_p3_outputs
from p3_common import coverage_for_route,relay_energy,evaluate_plan,save_basic_figures

OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"outputs"); FIG=os.path.join(os.path.dirname(os.path.abspath(__file__)),"figures")
os.makedirs(OUT,exist_ok=True); os.makedirs(FIG,exist_ok=True)

def perturbed(b,loss):
    x=dict(b)
    for key in ("direct","access","backhaul"): x[key]=b[key]-loss
    return x

def main():
    routes,boxes,o01,services,arr,transform,budget,node_map,specs,rspec,rfleet,rstock=prepare_context(); pool=candidate_pool(routes,o01,services,arr,transform,n_each=18)
    scenarios=[("基准",0.0),("中等衰落",5.0),("强衰落",10.0)]
    for r in routes:
        candrows=[]
        for p in pool[r["route_id"]]:
            covs=[coverage_for_route(r,p,node_map,perturbed(budget,loss),arr,transform) for _,loss in scenarios]
            worst=max(c["interrupted_s"] for c in covs); avg=sum(c["interrupted_s"] for c in covs)/len(covs)
            e=relay_energy(rspec,p,o01,r["T_route_s"]+float(rspec["建链时间"]))[0] if any(c["relay_need"] for c in covs) else 0.0
            candrows.append((worst,avg,e,p,covs))
        candrows.sort(key=lambda z:(z[0],z[1],z[2],z[3]["height_m"]))
        worst,avg,e,p,covs=candrows[0]; nominal=covs[0]
        r["_coverage"]={**nominal,"robust_worst_interrupt_s":worst}; r["_relay"]=p; r["_relay_energy"]=e
    assignments={r["route_id"]:{**r["_coverage"],"relay":r["_relay"],"relay_energy":r["_relay_energy"]} for r in routes}; plan=evaluate_plan(routes,assignments,rspec,rfleet,rstock,o01,boxes)
    scen=[]
    for name,loss in scenarios:
        total=0.0; relay_count=0
        for r in routes:
            c=coverage_for_route(r,r["_relay"],node_map,perturbed(budget,loss),arr,transform); total+=c["interrupted_s"]; relay_count+=int(c["relay_need"])
        scen.append({"情景":name,"附加链路损耗_dB":loss,"通信中断_s":total,"中继架次":relay_count,"中继容量C=1可行":"需逐时段检查","中继容量C=2可行":"需逐时段检查"})
    write_p3_outputs("p3-4pro",OUT,routes,plan,boxes,scen)
    summary=["问题三 p3-4pro：链路损耗扰动与中继容量鲁棒联合调度",f"路线数：{len(routes)}",f"名义通信中断(s)：{plan['f'][5]:.2f}",f"最坏情景通信中断(s)：{max(x['通信中断_s'] for x in scen):.2f}",f"联合完成时间(s)：{plan['f'][1]:.2f}",f"总能耗(kWh)：{plan['f'][2]:.3f}",f"中继架次：{plan['f'][4]}","情景：基准、5 dB附加衰落、10 dB附加衰落；通过最小化最坏通信中断选择中继点。"]
    with open(os.path.join(OUT,"p3-4pro_summary.txt"),"w",encoding="utf-8") as f:f.write("\n".join(summary))
    save_basic_figures(FIG,"p3-4pro",routes,assignments,plan["relay_schedule"],o01,services,boxes,plan,node_map)
    print("\n".join(summary))

if __name__=="__main__":main()

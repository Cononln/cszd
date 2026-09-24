# -*- coding: utf-8 -*-
"""问题三方法2：联合随机局部搜索（ALNS风格扰动-修复）。

以问题二运输方案为初始解，把每条架次的中继点/高度作为决策变量；候选覆盖
不足时更换悬停点，覆盖可行后再以通信中断、及时性、联合完工时间、总能耗、
运输/中继架次的加权和进行接受判定，并保存非支配解集。
"""
import os, sys, random
import numpy as np
import pandas as pd

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,ROOT)
from q00 import load_nodes, load_relay_drone, load_comm_params
from p3_common import (read_base_solution, load_dem_array, _comm_budget, make_node_map,
                       candidate_relays, coverage_for_route, evaluate_plan, save_basic_figures,
                       relay_energy)

OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"outputs"); FIG=os.path.join(os.path.dirname(os.path.abspath(__file__)),"figures")
os.makedirs(OUT,exist_ok=True); os.makedirs(FIG,exist_ok=True)
SEED=20260923

def score(plan, w=(1e-4,1e-5,1.0,80.0,120.0,3.0,2.0)):
    f=plan["f"]; return w[0]*f[0]+w[1]*f[1]+w[2]*f[2]+w[3]*f[3]+w[4]*f[4]+w[5]*f[5]+w[6]*f[6]

def dominates(a,b):
    return all(x<=y+1e-9 for x,y in zip(a,b)) and any(x<y-1e-9 for x,y in zip(a,b))

def main():
    rng=random.Random(SEED); routes, sorties, boxes=read_base_solution("q2_1")
    o01,services=load_nodes(); arr,transform,bounds=load_dem_array(); rspec_df,rfleet,rstock=load_relay_drone(); rspec=rspec_df.iloc[0]
    budget=_comm_budget(load_comm_params()); node_map=make_node_map(o01,services); cand=candidate_relays(routes,o01,services)
    # 为每条路线保留通信中断最少的候选池，减少搜索规模
    pools={}; cache={}
    for r in routes:
        vals=[]
        for p in cand:
            c=coverage_for_route(r,p,node_map,budget,arr,transform); e=relay_energy(rspec,p,o01,r["T_route_s"]+float(rspec["建链时间"]))[0] if c["relay_need"] else 0.0
            vals.append((c,p,e))
        vals.sort(key=lambda z:(z[0]["interrupted_s"],z[2],z[1]["height_m"]))
        pools[r["route_id"]]=vals[:min(18,len(vals))]
    # 初始解选择池首项；迭代中以“破坏多条路线+贪婪修复”扰动
    idx={rid:0 for rid in pools}
    def build():
        a={}
        for r in routes:
            c,p,e=pools[r["route_id"]][idx[r["route_id"]]]; a[r["route_id"]]={**c,"relay":p,"relay_energy":e}
        return a
    cur_assign=build(); cur=evaluate_plan(routes,cur_assign,rspec,rfleet,rstock,o01,boxes); best=cur; best_assign=cur_assign.copy(); archive=[]; history=[]
    for it in range(1,101):
        old=idx.copy(); changed=rng.randint(1,max(1,min(5,len(routes))))
        for rid in rng.sample(list(idx),changed):
            # 70% 在邻域移动，30% 大范围重置
            step=rng.choice([-2,-1,1,2]) if rng.random()<0.7 else rng.randint(-8,8)
            idx[rid]=max(0,min(len(pools[rid])-1,idx[rid]+step))
        cand_assign=build(); cand_plan=evaluate_plan(routes,cand_assign,rspec,rfleet,rstock,o01,boxes)
        T=max(0.02,2.5*(1-it/100))
        delta=score(cand_plan)-score(cur)
        if delta<=0 or rng.random()<np.exp(-delta/T): cur_assign,cur= cand_assign,cand_plan
        else: idx=old
        if score(cur)<score(best): best,best_assign=cur,cur_assign.copy()
        history.append({"迭代":it,"目标值":score(cur),"通信中断_s":cur["f"][5],"硬时限违反_s":cur["f"][6],"联合完成_s":cur["f"][1],"总能耗_kWh":cur["f"][2],"中继架次":cur["f"][4]})
        vec=tuple(cur["f"][:7]);
        if not any(dominates(x["vec"],vec) for x in archive):
            archive=[x for x in archive if not dominates(vec,x["vec"])]
            archive.append({"vec":vec,"plan":cur,"assign":cur_assign.copy()})
    plan=best; assignments=best_assign
    # 输出
    pd.DataFrame(history).to_csv(os.path.join(OUT,"p3-2_search_history.csv"),index=False,encoding="utf-8-sig")
    relay_map={x["route_id"]:x for x in plan["relay_schedule"]}
    pd.DataFrame([{"路线编号":r["route_id"],"架次编号":r["sortie_id"],"机型编号":r["机型编号"],"停靠序列":"O01->"+"->".join(r["stops"])+"->O01","起飞_s":relay_map[r["route_id"]].get("transport_start",r["start"]),"返航_s":relay_map[r["route_id"]].get("transport_end",r["end"]),"通信中断_s":assignments[r["route_id"]]["interrupted_s"],"覆盖率":assignments[r["route_id"]]["coverage_ratio"],"是否需要中继":assignments[r["route_id"]]["relay_need"],"中继点":assignments[r["route_id"]]["relay"]["name"],"经度":assignments[r["route_id"]]["relay"]["lon"],"纬度":assignments[r["route_id"]]["relay"]["lat"],"悬停高度_m":assignments[r["route_id"]]["relay"]["height_m"]} for r in routes]).to_csv(os.path.join(OUT,"p3-2_routes.csv"),index=False,encoding="utf-8-sig")
    pd.DataFrame(plan["relay_schedule"]).to_csv(os.path.join(OUT,"p3-2_relay_schedule.csv"),index=False,encoding="utf-8-sig")
    timeline=[]
    for r in routes:
        x=relay_map[r["route_id"]]; ts=x.get("transport_start",r["start"]); te=x.get("transport_end",r["end"])
        timeline.append({"资源编号":r["uav_id"],"资源类型":"运输无人机","任务编号":r["sortie_id"],"活动":"运输架次","开始_s":ts,"结束_s":te})
    for x in plan["relay_schedule"]:
        if x["relay_id"]!="无需中继":
            timeline.append({"资源编号":x["relay_id"],"资源类型":"中继无人机","任务编号":x["route_id"],"活动":"中继飞行与服务","开始_s":x["start"],"结束_s":x["end"]})
            timeline.append({"资源编号":x["battery_id"],"资源类型":"中继能源组件","任务编号":x["route_id"],"活动":"充电周转","开始_s":x["end"],"结束_s":x["end"]+float(rstock["等效完全充电时间"])})
    pd.DataFrame(timeline).to_csv(os.path.join(OUT,"p3-2_resource_timeline.csv"),index=False,encoding="utf-8-sig")
    pd.DataFrame([{"方案编号":i+1,"及时性":x["vec"][0],"联合完成_s":x["vec"][1],"总能耗_kWh":x["vec"][2],"运输架次":x["vec"][3],"中继架次":x["vec"][4],"通信中断_s":x["vec"][5],"硬时限违反_s":x["vec"][6]} for i,x in enumerate(archive)]).to_csv(os.path.join(OUT,"p3-2_pareto_front.csv"),index=False,encoding="utf-8-sig")
    comm=[]
    for r in routes:
        for k,s in enumerate(assignments[r["route_id"]]["states"]): comm.append({"架次编号":r["sortie_id"],"路线编号":r["route_id"],"采样点序号":k,"通信状态":s,"相对时间_s":k*r["T_route_s"]/max(len(assignments[r["route_id"]]["states"])-1,1)})
    pd.DataFrame(comm).to_csv(os.path.join(OUT,"p3-2_communication_states.csv"),index=False,encoding="utf-8-sig")
    pd.DataFrame([{"货箱编号":bid,"预测送达_s":t} for bid,t in plan["deliveries"].items()]).to_csv(os.path.join(OUT,"p3-2_box_delivery.csv"),index=False,encoding="utf-8-sig")
    summary=["问题三 p3-2：联合随机局部搜索",f"迭代次数：{len(history)}；保留非支配解：{len(archive)}",f"通信中断总时长(s)：{plan['f'][5]:.2f}",f"硬时限违反量(s)：{plan['f'][6]:.2f}",f"联合完成时间(s)：{plan['f'][1]:.2f}",f"运输能耗(kWh)：{plan['transport_energy']:.3f}",f"中继能耗(kWh)：{plan['relay_energy']:.3f}",f"运输架次：{plan['f'][3]}；中继架次：{plan['f'][4]}","接受准则：通信连续性与硬时限优先，随后按及时性、联合完成时间、能耗和架次加权。"]
    with open(os.path.join(OUT,"p3-2_summary.txt"),"w",encoding="utf-8") as f:f.write("\n".join(summary))
    save_basic_figures(FIG,"p3-2",routes,assignments,plan["relay_schedule"],o01,services,boxes,plan,node_map)
    # 搜索收敛图和二维Pareto图
    h=pd.DataFrame(history); import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(9,4.5)); ax.plot(h["迭代"],h["目标值"],color="#2a78d6",lw=1.8); ax.set_xlabel("迭代"); ax.set_ylabel("加权目标值"); ax.set_title("p3-2 局部搜索收敛曲线",loc="left",fontweight="bold"); from q00 import style_ax,savefig; style_ax(ax,"y"); savefig(fig,os.path.join(FIG,"p3-2_06_搜索收敛.png"))
    pf=pd.DataFrame([x["vec"] for x in archive]); fig,ax=plt.subplots(figsize=(7,5)); ax.scatter(pf[1]/3600,pf[2],c=pf[5],cmap="viridis",s=55,edgecolor="white"); ax.set_xlabel("联合完成时间 (h)"); ax.set_ylabel("总能耗 (kWh)"); ax.set_title("p3-2 非支配解：时间—能耗—通信中断",loc="left",fontweight="bold"); style_ax(ax,"both"); savefig(fig,os.path.join(FIG,"p3-2_07_帕累托前沿.png"))
    print("\n".join(summary))

if __name__=="__main__":main()

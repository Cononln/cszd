# -*- coding: utf-8 -*-
"""问题三增强方案1：通信感知的路线访问顺序—中继位置联合优化。"""
import os,sys
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,ROOT)
from p3pro_common import prepare_context,candidate_pool,route_variants,assignment_from_routes,write_p3_outputs
from p3_common import evaluate_plan,save_basic_figures
from q2_common import load_leg_geometry_table

OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"outputs"); FIG=os.path.join(os.path.dirname(os.path.abspath(__file__)),"figures")
os.makedirs(OUT,exist_ok=True); os.makedirs(FIG,exist_ok=True)

def main():
    routes,boxes,o01,services,arr,transform,budget,node_map,specs,rspec,rfleet,rstock=prepare_context(); leg_geo,_,_=load_leg_geometry_table()
    pool=candidate_pool(routes,o01,services,arr,transform,n_each=14)
    routes=route_variants(routes,leg_geo,specs,node_map,budget,arr,transform,o01,rspec,pool)
    assignments=assignment_from_routes(routes); plan=evaluate_plan(routes,assignments,rspec,rfleet,rstock,o01,boxes)
    write_p3_outputs("p3-3pro",OUT,routes,plan,boxes)
    relay_map={x["route_id"]:x for x in plan["relay_schedule"]}; timeline=[]
    for r in routes:
        x=relay_map[r["route_id"]]; timeline.append({"资源编号":r.get("uav_id","运输机"),"资源类型":"运输无人机","任务编号":r.get("sortie_id",r["route_id"]),"活动":"运输架次","开始_s":x.get("transport_start",r["start"]),"结束_s":x.get("transport_end",r["end"])})
    for x in plan["relay_schedule"]:
        if x["relay_id"]!="无需中继": timeline.append({"资源编号":x["relay_id"],"资源类型":"中继无人机","任务编号":x["route_id"],"活动":"中继飞行与服务","开始_s":x["start"],"结束_s":x["end"]})
    import pandas as pd
    pd.DataFrame(timeline).to_csv(os.path.join(OUT,"p3-3pro_resource_timeline.csv"),index=False,encoding="utf-8-sig")
    summary=["问题三 p3-3pro：通信感知路线顺序—中继位置联合优化",f"路线数：{len(routes)}",f"通信中断(s)：{plan['f'][5]:.2f}",f"硬时限违反(s)：{plan['f'][6]:.2f}",f"联合完成时间(s)：{plan['f'][1]:.2f}",f"总能耗(kWh)：{plan['f'][2]:.3f}",f"中继架次：{plan['f'][4]}","改进点：对多服务区架次同时枚举访问顺序，并把通信覆盖和中继能耗纳入路线选择。"]
    with open(os.path.join(OUT,"p3-3pro_summary.txt"),"w",encoding="utf-8") as f:f.write("\n".join(summary))
    save_basic_figures(FIG,"p3-3pro",routes,assignments,plan["relay_schedule"],o01,services,boxes,plan,node_map)
    print("\n".join(summary))

if __name__=="__main__":main()

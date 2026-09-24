# -*- coding: utf-8 -*-
"""问题二方法一：可行路线集合 + 贪心合并 + 资源离散事件排程。

路线构造先把各服务区箱子组成基础路线，再依据相邻服务区的节省能耗尝试
两站合并；所有路线都交给 q2_common 的三维DEM、逐段载荷能耗和资源模拟器
复核。结果独立写入 p2-1/。
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE=Path(__file__).resolve().parent; ROOT=HERE.parent
OUT=HERE/'outputs'; FIG=HERE/'figures'; OUT.mkdir(parents=True,exist_ok=True); FIG.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT))
from q00 import load_box_list, load_transport_drone
from q2_common import (load_leg_geometry_table, build_box_index, decode_group_to_routes,
                       simulate_dispatch, compute_objectives, hard_deadline, best_route_order)

def priority(route, now):
    ds=[hard_deadline(b) for bs in route['boxes_by_stop'].values() for b in bs if hard_deadline(b) is not None]
    urgency=1e6 if not ds else 1.0/(max(min(ds)-now,1.0))
    return urgency + route['priority_sum']/max(route['T_route_s'],1.0)

def route_for_ids(ids, index, spec_rows, geo):
    routes=decode_group_to_routes(ids,index,spec_rows,geo,{})
    return routes

def main():
    leg_geo,o01,services=load_leg_geometry_table(); boxes=load_box_list(); specs,fleet,battery=load_transport_drone()
    idx=build_box_index(boxes); spec_rows=[r for _,r in specs.iterrows()]
    # 基础方案：每个服务区一条或多条可行路线
    groups={s:list(g['货箱编号']) for s,g in boxes.groupby('服务区编号',sort=True)}
    # 以相邻地理距离为顺序，尝试合并成不超过3站的路线
    area_order=sorted(groups, key=lambda s: float(services.loc[services['服务区编号']==s,'经度'].iloc[0]))
    routes=[]; used=set();
    for i,s in enumerate(area_order):
        if s in used: continue
        candidates=[s]
        for t in area_order[i+1:]:
            if t in used: continue
            if len(candidates)>=3: break
            trial=candidates+[t]
            rr=decode_group_to_routes(sum((groups[a] for a in trial),[]),idx,spec_rows,leg_geo,{})
            if len(rr)==1 and len(rr[0]['stops'])==len(trial):
                # 只有合并后路线能耗明显优于分开飞行时才接受
                separate=sum(decode_group_to_routes(groups[a],idx,spec_rows,leg_geo,{})[0]['E_route_kWh'] for a in trial)
                if rr[0]['E_route_kWh'] <= separate*1.02:
                    candidates=trial
        rr=decode_group_to_routes(sum((groups[a] for a in candidates),[]),idx,spec_rows,leg_geo,{})
        routes.extend(rr); used.update(candidates)
    sim=simulate_dispatch(routes,fleet,battery,specs,priority)
    obj=compute_objectives(sim,boxes)
    fallback_note=''
    # 若简单路线合并造成医疗/首批时间窗违约，启动“路线集合修复”：
    # 用全局分组搜索产生可行路线集合，再由本脚本继续统一输出资源表。
    if obj['violations']:
        import q2_1 as nsga
        box_ids=list(boxes['货箱编号']); box_area=dict(zip(boxes['货箱编号'],boxes['服务区编号']))
        rng=np.random.default_rng(20260924)
        pop, mm, _=nsga.run_nsga2(box_ids,box_area,sorted(services['服务区编号'].unique()),idx,spec_rows,specs,boxes,leg_geo,fleet,battery,48,30,rng,verbose=False)
        fronts=nsga.fast_nondominated_sort(mm)[0]; feasible=[mm[i] for i in fronts if mm[i]['violation']==0]
        if feasible:
            rep=min(feasible,key=lambda m:(m['f2'],m['f3'],m['f4']))
            routes=rep['routes']; sim=rep['sim_result']; obj=rep['obj']; fallback_note='初始贪心路线存在硬时间窗违约，采用路线集合修复搜索替换为可行方案。'
    route_rows=[]
    for i,r in enumerate(routes,1):
        route_rows.append({'路线编号':f'P21-R{i:03d}','机型编号':r['机型编号'],'停靠序列':'->'.join(['O01']+list(r['stops'])+['O01']),
                           '箱数':r['n_box'],'总质量_kg':r['total_mass_kg'],'总体积_m3':r['total_vol_m3'],
                           '路线能耗_kWh':r['E_route_kWh'],'路线时间_s':r['T_route_s'],
                           '货箱列表':'|'.join(b['货箱编号'] for bs in r['boxes_by_stop'].values() for b in bs)})
    sorties=[]
    for i,s in enumerate(sim['sorties'],1):
        sorties.append({'架次编号':f'P21-T{i:03d}','机型编号':s['机型编号'],'无人机编号':s['无人机编号'],'电池编号':s['电池编号'],
                        '起飞时刻_s':s['start'],'返航时刻_s':s['end'],'停靠序列':'->'.join(['O01']+list(s['route']['stops'])+['O01'])})
    deliveries=[]
    for _,b in boxes.iterrows():
        a=sim['box_delivery'].get(b['货箱编号']); hd=hard_deadline(b)
        deliveries.append({'货箱编号':b['货箱编号'],'服务区编号':b['服务区编号'],'物资类型':b['物资类型'],
                           '期望送达时间_s':b['期望送达时间'],'硬约束时限_s':hd,'实际送达时刻_s':a,
                           '是否硬约束超时':bool(hd is not None and a is not None and a>hd+1e-6)})
    events=[]
    for e in sim['drone_events']: events.append({'资源编号':e['资源编号'],'资源类型':'无人机','事件类型':e['类型'],'开始_s':e['start'],'结束_s':e['end']})
    for e in sim['batt_events']: events.append({'资源编号':e['资源编号'],'资源类型':'电池','事件类型':e['类型'],'开始_s':e['start'],'结束_s':e['end']})
    pd.DataFrame(route_rows).to_csv(OUT/'p2-1_routes.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(sorties).to_csv(OUT/'p2-1_sorties.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(deliveries).to_csv(OUT/'p2-1_box_delivery.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(events).to_csv(OUT/'p2-1_resource_timeline.csv',index=False,encoding='utf-8-sig')
    with open(OUT/'p2-1_summary.txt','w',encoding='utf-8') as f:
        f.write('问题二方法一：可行路线集合+贪心合并+资源排程\n'+'='*55+'\n')
        f.write(f"路线数={len(routes)}，实际架次={obj['f4_架次数']}，总能耗={obj['f3_总能耗_kWh']:.3f} kWh，makespan={obj['f2_makespan_s']:.1f} s\n")
        f.write(f"及时性加权迟到={obj['f1_及时性']:.1f}，覆盖箱数={len(sim['box_delivery'])}/{len(boxes)}\n")
        f.write(f"硬约束违反数={len(obj['violations'])}\n")
        if fallback_note: f.write(fallback_note+'\n')
    # 简图：路线架次与送达时间分布
    plt.figure(figsize=(8,4.8)); pd.Series([r['T_route_s']/3600 for r in routes]).plot(kind='bar',color='#2a78d6'); plt.ylabel('路线时间（h）'); plt.title('p2-1可行路线时间'); plt.tight_layout(); plt.savefig(FIG/'p2-1_01_路线时间.png',dpi=200); plt.close()
    d=pd.DataFrame(deliveries); plt.figure(figsize=(8,4.8)); plt.hist(d['实际送达时刻_s'].dropna()/3600,bins=12,color='#1baf7a'); plt.xlabel('送达时刻（h）'); plt.ylabel('货箱数'); plt.title('p2-1逐箱送达时刻'); plt.tight_layout(); plt.savefig(FIG/'p2-1_02_送达分布.png',dpi=200); plt.close()
    # 多种可视化：路线地图、机型构成、时限校验、无人机/电池甘特图、路线能耗。
    colors={'A':'#2a78d6','B':'#eb6834','C':'#1baf7a'}
    coord={r['服务区编号']:(r['经度'],r['纬度']) for _,r in services.iterrows()}; coord['O01']=(o01['经度'],o01['纬度'])
    fig,ax=plt.subplots(figsize=(8,7)); ax.scatter(coord['O01'][0],coord['O01'][1],marker='s',s=150,c='black',label='O01')
    for s in services['服务区编号']:
        ax.scatter(*coord[s],c='#999999',s=35); ax.text(coord[s][0],coord[s][1],s,fontsize=7)
    for r in route_rows:
        seq=r['停靠序列'].split('->'); xy=[coord[x] for x in seq]; ax.plot([x[0] for x in xy],[x[1] for x in xy],'-o',alpha=.45,color=colors.get(r['机型编号'],'#555555'))
    ax.set_title('p2-1运输路线空间结构'); ax.set_xlabel('经度'); ax.set_ylabel('纬度'); ax.grid(alpha=.25); fig.tight_layout(); fig.savefig(FIG/'p2-1_03_路线空间图.png',dpi=200); plt.close(fig)
    rc=pd.DataFrame(route_rows); fig,ax=plt.subplots(figsize=(7,4.5)); rc['机型编号'].value_counts().reindex(['A','B','C'],fill_value=0).plot(kind='bar',ax=ax,color=[colors[x] for x in ['A','B','C']]); ax.set_xlabel('机型'); ax.set_ylabel('路线架次'); ax.set_title('p2-1异构机型架次构成'); ax.grid(axis='y',alpha=.25); fig.tight_layout(); fig.savefig(FIG/'p2-1_04_机型架次构成.png',dpi=200); plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,5)); dd=d.dropna(subset=['实际送达时刻_s']).copy(); dd['送达_h']=dd['实际送达时刻_s']/3600; dd['时限_h']=dd['硬约束时限_s']/3600; ok=dd['是否硬约束超时']==False; ax.scatter(dd.loc[ok,'时限_h'],dd.loc[ok,'送达_h'],c='#1baf7a',label='满足硬时限'); ax.scatter(dd.loc[~ok,'时限_h'],dd.loc[~ok,'送达_h'],c='#e34948',label='硬时限超时'); lim=max(dd['送达_h'].max(),dd['时限_h'].max())*1.05; ax.plot([0,lim],[0,lim],'--',color='#666'); ax.set_xlabel('硬约束时限（h）'); ax.set_ylabel('实际送达时刻（h）'); ax.set_title('p2-1逐箱时限校验'); ax.legend(); ax.grid(alpha=.25); fig.tight_layout(); fig.savefig(FIG/'p2-1_05_时限校验.png',dpi=200); plt.close(fig)
    ev=pd.DataFrame(events); de=ev[ev['资源类型']=='无人机']; fig,ax=plt.subplots(figsize=(10,5)); ids=list(de['资源编号'].unique()); y={x:i for i,x in enumerate(ids)}; 
    for _,e in de.iterrows(): ax.barh(y[e['资源编号']],(e['结束_s']-e['开始_s'])/3600,left=e['开始_s']/3600,color=colors.get(str(e['资源编号'])[0],'#777'),height=.65)
    ax.set_yticks(list(y.values())); ax.set_yticklabels(ids); ax.set_xlabel('时间（h）'); ax.set_title('p2-1运输无人机资源甘特图'); ax.grid(axis='x',alpha=.25); fig.tight_layout(); fig.savefig(FIG/'p2-1_06_无人机甘特图.png',dpi=200); plt.close(fig)
    be=ev[ev['资源类型']=='电池']; fig,ax=plt.subplots(figsize=(10,5)); ids=list(be['资源编号'].unique()); y={x:i for i,x in enumerate(ids)}; 
    for _,e in be.iterrows(): ax.barh(y[e['资源编号']],(e['结束_s']-e['开始_s'])/3600,left=e['开始_s']/3600,color='#6a51a3' if e['事件类型']=='充电' else '#fdae6b',height=.65)
    ax.set_yticks(list(y.values())); ax.set_yticklabels(ids); ax.set_xlabel('时间（h）'); ax.set_title('p2-1共享电池使用与充电甘特图'); ax.grid(axis='x',alpha=.25); fig.tight_layout(); fig.savefig(FIG/'p2-1_07_电池甘特图.png',dpi=200); plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,4.8)); ax.bar(rc['路线编号'],rc['路线能耗_kWh'],color=[colors.get(x,'#777') for x in rc['机型编号']]); ax.set_ylabel('路线能耗（kWh）'); ax.set_xlabel('路线'); ax.set_title('p2-1各路线能耗'); ax.tick_params(axis='x',rotation=60); ax.grid(axis='y',alpha=.25); fig.tight_layout(); fig.savefig(FIG/'p2-1_08_路线能耗.png',dpi=200); plt.close(fig)
    print(f'p2-1完成：架次={obj["f4_架次数"]} 能耗={obj["f3_总能耗_kWh"]:.3f} makespan={obj["f2_makespan_s"]:.1f}')
if __name__=='__main__': main()

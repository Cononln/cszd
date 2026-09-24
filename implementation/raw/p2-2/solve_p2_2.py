# -*- coding: utf-8 -*-
"""问题二方法二：全局NSGA-II分组编码调度。

复用 q2_1.py 中已经验证过的全局染色体、解码、连续通信前的资源模拟和
Deb约束支配逻辑，但把所有结果独立保存到 p2-2/，不改写q2_1输出。
"""
from pathlib import Path
import sys, time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE=Path(__file__).resolve().parent; ROOT=HERE.parent
OUT=HERE/'outputs'; FIG=HERE/'figures'; OUT.mkdir(parents=True,exist_ok=True); FIG.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT))
import q2_1 as q  # noqa: E402
from q00 import load_box_list, load_transport_drone
from q2_common import load_leg_geometry_table, build_box_index, hard_deadline

POP=48; GEN=35; SEED=20260925

def main():
    leg,o01,services=load_leg_geometry_table(); boxes=load_box_list(); specs,fleet,battery=load_transport_drone()
    box_ids=list(boxes['货箱编号']); box_area=dict(zip(boxes['货箱编号'],boxes['服务区编号']))
    areas=sorted(services['服务区编号'].unique()); index=build_box_index(boxes); spec_rows=[r for _,r in specs.iterrows()]
    rng=np.random.default_rng(SEED); t0=time.time()
    pop, metrics, times=q.run_nsga2(box_ids,box_area,areas,index,spec_rows,specs,boxes,leg,fleet,battery,POP,GEN,rng,verbose=True)
    fronts=q.fast_nondominated_sort(metrics); f0=[metrics[i] for i in fronts[0]]; feasible=[m for m in f0 if m['violation']==0]
    pool=feasible if feasible else f0; rep=min(pool,key=lambda m:(m['f4'],m['f3'],m['f2']))
    # 方案明细
    route_rows=[]
    for i,r in enumerate(rep['routes'],1):
        route_rows.append({'路线编号':f'P22-R{i:03d}','机型编号':r['机型编号'],'停靠序列':'->'.join(['O01']+list(r['stops'])+['O01']),
                           '箱数':r['n_box'],'总质量_kg':r['total_mass_kg'],'总体积_m3':r['total_vol_m3'],
                           '路线能耗_kWh':r['E_route_kWh'],'路线时间_s':r['T_route_s'],
                           '货箱列表':'|'.join(b['货箱编号'] for bs in r['boxes_by_stop'].values() for b in bs)})
    sim=rep['sim_result']; sortie_rows=[]
    for i,s in enumerate(sim['sorties'],1):
        sortie_rows.append({'架次编号':f'P22-T{i:03d}','机型编号':s['机型编号'],'无人机编号':s['无人机编号'],'电池编号':s['电池编号'],
                            '起飞时刻_s':s['start'],'返航时刻_s':s['end'],'停靠序列':'->'.join(['O01']+list(s['route']['stops'])+['O01'])})
    delivery=[]
    for _,b in boxes.iterrows():
        a=sim['box_delivery'].get(b['货箱编号']); hd=hard_deadline(b)
        delivery.append({'货箱编号':b['货箱编号'],'服务区编号':b['服务区编号'],'物资类型':b['物资类型'],'期望送达时间_s':b['期望送达时间'],
                         '硬约束时限_s':hd,'实际送达时刻_s':a,'是否硬约束超时':bool(hd is not None and a is not None and a>hd+1e-6)})
    events=[]
    for e in sim['drone_events']: events.append({'资源编号':e['资源编号'],'资源类型':'无人机','事件类型':e['类型'],'开始_s':e['start'],'结束_s':e['end']})
    for e in sim['batt_events']: events.append({'资源编号':e['资源编号'],'资源类型':'电池','事件类型':e['类型'],'开始_s':e['start'],'结束_s':e['end']})
    pd.DataFrame(route_rows).to_csv(OUT/'p2-2_routes.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(sortie_rows).to_csv(OUT/'p2-2_sorties.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(delivery).to_csv(OUT/'p2-2_box_delivery.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(events).to_csv(OUT/'p2-2_resource_timeline.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame([{'f1_及时性':m['f1'],'f2_makespan_s':m['f2'],'f3_总能耗_kWh':m['f3'],'f4_架次数':m['f4'],'违反量':m['violation']} for m in f0]).to_csv(OUT/'p2-2_pareto_front.csv',index=False,encoding='utf-8-sig')
    with open(OUT/'p2-2_summary.txt','w',encoding='utf-8') as f:
        f.write('问题二方法二：全局NSGA-II分组编码\n'+'='*55+'\n')
        f.write(f'种群={POP}，代数={GEN}，随机种子={SEED}，耗时={time.time()-t0:.1f}s\n')
        f.write(f'代表解：及时性={rep["f1"]:.1f}，makespan={rep["f2"]:.1f}s，能耗={rep["f3"]:.3f}kWh，架次={rep["f4"]:.0f}\n')
        f.write(f'前沿规模={len(f0)}，其中可行解={len(feasible)}，送达箱数={len(sim["box_delivery"])}/{len(boxes)}，硬约束违反={len(rep["obj"]["violations"])}\n')
    # Pareto散点与路线时间图
    ff=pd.DataFrame([{'E':m['f3'],'N':m['f4'],'M':m['f2']/3600} for m in f0]); plt.figure(figsize=(7,5)); plt.scatter(ff['E'],ff['N'],c=ff['M'],cmap='viridis',s=60); plt.xlabel('总能耗（kWh）'); plt.ylabel('架次数'); plt.colorbar(label='makespan（h）'); plt.title('p2-2 NSGA-II非支配前沿'); plt.tight_layout(); plt.savefig(FIG/'p2-2_01_帕累托前沿.png',dpi=200); plt.close()
    plt.figure(figsize=(8,4.8)); plt.bar(range(1,len(route_rows)+1),[r['路线时间_s']/3600 for r in route_rows],color='#eb6834'); plt.xlabel('路线编号'); plt.ylabel('路线时间（h）'); plt.title('p2-2代表解路线时间'); plt.tight_layout(); plt.savefig(FIG/'p2-2_02_路线时间.png',dpi=200); plt.close()
    colors={'A':'#2a78d6','B':'#eb6834','C':'#1baf7a'}; rc=pd.DataFrame(route_rows); dd=pd.DataFrame(delivery); ev=pd.DataFrame(events)
    coord={r['服务区编号']:(r['经度'],r['纬度']) for _,r in services.iterrows()}; coord['O01']=(o01['经度'],o01['纬度'])
    fig,ax=plt.subplots(figsize=(8,7)); ax.scatter(coord['O01'][0],coord['O01'][1],marker='s',s=150,c='black',label='O01')
    for s in services['服务区编号']:
        ax.scatter(*coord[s],c='#999999',s=35); ax.text(coord[s][0],coord[s][1],s,fontsize=7)
    for r in route_rows:
        seq=r['停靠序列'].split('->'); xy=[coord[x] for x in seq]; ax.plot([x[0] for x in xy],[x[1] for x in xy],'-o',alpha=.45,color=colors.get(r['机型编号'],'#555'))
    ax.set_title('p2-2 NSGA-II代表解路线空间结构'); ax.set_xlabel('经度'); ax.set_ylabel('纬度'); ax.grid(alpha=.25); fig.tight_layout(); fig.savefig(FIG/'p2-2_03_路线空间图.png',dpi=200); plt.close(fig)
    fig,ax=plt.subplots(figsize=(7,4.5)); rc['机型编号'].value_counts().reindex(['A','B','C'],fill_value=0).plot(kind='bar',ax=ax,color=[colors[x] for x in ['A','B','C']]); ax.set_xlabel('机型'); ax.set_ylabel('路线架次'); ax.set_title('p2-2异构机型架次构成'); ax.grid(axis='y',alpha=.25); fig.tight_layout(); fig.savefig(FIG/'p2-2_04_机型架次构成.png',dpi=200); plt.close(fig)
    x=dd.dropna(subset=['实际送达时刻_s']).copy(); x['送达_h']=x['实际送达时刻_s']/3600; x['时限_h']=x['硬约束时限_s']/3600; ok=x['是否硬约束超时']==False; fig,ax=plt.subplots(figsize=(9,5)); ax.scatter(x.loc[ok,'时限_h'],x.loc[ok,'送达_h'],c='#1baf7a',label='满足硬时限'); ax.scatter(x.loc[~ok,'时限_h'],x.loc[~ok,'送达_h'],c='#e34948',label='硬时限超时'); lim=max(x['送达_h'].max(),x['时限_h'].max())*1.05; ax.plot([0,lim],[0,lim],'--',color='#666'); ax.set_xlabel('硬约束时限（h）'); ax.set_ylabel('实际送达时刻（h）'); ax.set_title('p2-2逐箱时限校验'); ax.legend(); ax.grid(alpha=.25); fig.tight_layout(); fig.savefig(FIG/'p2-2_05_时限校验.png',dpi=200); plt.close(fig)
    de=ev[ev['资源类型']=='无人机']; fig,ax=plt.subplots(figsize=(10,5)); ids=list(de['资源编号'].unique()); y={z:i for i,z in enumerate(ids)}
    for _,e in de.iterrows(): ax.barh(y[e['资源编号']],(e['结束_s']-e['开始_s'])/3600,left=e['开始_s']/3600,color=colors.get(str(e['资源编号'])[0],'#777'),height=.65)
    ax.set_yticks(list(y.values())); ax.set_yticklabels(ids); ax.set_xlabel('时间（h）'); ax.set_title('p2-2运输无人机资源甘特图'); ax.grid(axis='x',alpha=.25); fig.tight_layout(); fig.savefig(FIG/'p2-2_06_无人机甘特图.png',dpi=200); plt.close(fig)
    be=ev[ev['资源类型']=='电池']; fig,ax=plt.subplots(figsize=(10,5)); ids=list(be['资源编号'].unique()); y={z:i for i,z in enumerate(ids)}
    for _,e in be.iterrows(): ax.barh(y[e['资源编号']],(e['结束_s']-e['开始_s'])/3600,left=e['开始_s']/3600,color='#6a51a3' if e['事件类型']=='充电' else '#fdae6b',height=.65)
    ax.set_yticks(list(y.values())); ax.set_yticklabels(ids); ax.set_xlabel('时间（h）'); ax.set_title('p2-2共享电池使用与充电甘特图'); ax.grid(axis='x',alpha=.25); fig.tight_layout(); fig.savefig(FIG/'p2-2_07_电池甘特图.png',dpi=200); plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,4.8)); ax.bar(rc['路线编号'],rc['路线能耗_kWh'],color=[colors.get(x,'#777') for x in rc['机型编号']]); ax.set_ylabel('路线能耗（kWh）'); ax.set_xlabel('路线'); ax.set_title('p2-2代表解各路线能耗'); ax.tick_params(axis='x',rotation=60); ax.grid(axis='y',alpha=.25); fig.tight_layout(); fig.savefig(FIG/'p2-2_08_路线能耗.png',dpi=200); plt.close(fig)
    print(f'p2-2完成：架次={rep["f4"]:.0f} 能耗={rep["f3"]:.3f} makespan={rep["f2"]:.1f} 前沿={len(f0)}')
if __name__=='__main__': main()

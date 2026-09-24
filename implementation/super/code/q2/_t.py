# -*- coding: utf-8 -*-
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.route import precompute_all_legs
precompute_all_legs()
import q2.q2_main as M
t0=time.time()
tr = M.construct_initial()
print("construct %.2fs trips=%d"%(time.time()-t0, len(tr)))
ss, met0 = M.greedy_schedule_fast(tr)
met = M.solution_metrics(tr, ss)
print(met)
print(M.validate(tr, ss))
import collections
print(collections.Counter(t.gtype for t in tr))
lines=[]
for x in ss:
    t = tr[x["trip_idx"]]
    lines.append("T%02d %s %-26s n=%d m=%5.1f tf=%5.0f st=%7.1f en=%7.1f v=%6.0f dr=%s"%(
        x["trip_idx"], t.gtype, "+".join(t.stops), len(t.box_ids), t.sum_mass,
        t.arr_tfirst.min(), x["start"], x["start"]+t.dur, t.lateness(x["start"])[1],
        x["drone"]))
open("results/_t.txt","w",encoding="utf-8").write("\n".join(lines))

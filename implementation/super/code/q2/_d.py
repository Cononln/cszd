# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from common.data import load_boxes
b = load_boxes()
pd.set_option("display.width", 200)
b2 = b.sort_values(["sid","type","box"])
open("results/_d.txt","w",encoding="utf-8").write(b2.to_string())
open("results/_d2.txt","w",encoding="utf-8").write(
    b.groupby(["sid","type"]).agg(n=("box","size"), te=("t_exp","min"),
      tf=("t_first", lambda s: s.min())).to_string())

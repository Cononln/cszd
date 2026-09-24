# -*- coding: utf-8 -*-
"""一次性文本修补：还原被误写成换行的 \\ref 命令。"""
import io
import sys

BS = chr(92)
P = "texfile/6ErrorAnalysis.tex"
s = io.open(P, encoding="utf-8").read()

n = s.count("\nef{sec:")
s = s.replace("\nef{sec:", BS + "ref{sec:")
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("修复 %d 处" % n)

s = io.open(P, encoding="utf-8").read()
ok = all((BS + "ref{" + t + "}") in s
         for t in ("sec:q1-rho", "sec:q4-topsis", "sec:q4-partition"))
print("复核：", "OK" if ok and n == 3 else "失败")
sys.exit(0 if (ok and n == 3) else 1)

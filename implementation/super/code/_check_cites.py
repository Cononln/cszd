# -*- coding: utf-8 -*-
"""核对正文 \cite{} 与 book.bib 条目的一致性。"""
import glob
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

pat = re.compile(r"\\cite\{([^}]*)\}")
keys = set()
for f in glob.glob("texfile/*.tex"):
    t = open(f, encoding="utf-8").read()
    for m in pat.finditer(t):
        for k in m.group(1).split(","):
            k = k.strip()
            if k:
                keys.add(k)

bib = open("book.bib", encoding="utf-8").read()
have = set(re.findall(r"@\w+\{([^,]+),", bib))
print("cited :", len(keys))
print("in bib:", len(have))
print("bib not cited :", sorted(have - keys))
print("cited not in bib:", sorted(keys - have))

# super：进阶主实现

这套代码来自 `进阶版`，包含公共物理模块、Q1-Q4 求解、敏感性分析、结果表生成和现有数值结果。

## 环境

```powershell
python -m pip install -r implementation/super/requirements.txt
```

## 建议执行顺序

```powershell
python -m implementation.super.code.common.selftest
python implementation/super/code/q1/q1_solve.py
python implementation/super/code/q2/q2_main.py
python implementation/super/code/q3/q3_solve.py
python implementation/super/code/q4/q4_partition.py
python implementation/super/code/make_submission.py
```

所有代码从仓库根目录的 `data/raw/` 读取官方附件，数值结果写入 `implementation/super/results/`，提交工作簿写入 `implementation/super/结果提交.xlsx`。


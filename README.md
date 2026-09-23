# cszd

山区洪涝灾害下无人机运输与通信协同优化（数学建模 D 题）的协同建模仓库。

仓库当前为私有仓库。这里只保留赛题、官方数据、提交模板及本队生成的代码与结果；付费资料、内部资料和其他项目的 Git 历史不纳入版本控制。

## 问题拆分

| 子项目 | 任务 | 上游依赖 | 标准输出位置 |
| --- | --- | --- | --- |
| Q1 | 单点往返最大安全载荷与组批 | 原始数据 | `projects/q1_capacity_batching/outputs/` |
| Q2 | 异构运输无人机、多点多架次与共享电池联合调度 | Q1 | `projects/q2_transport_scheduling/outputs/` |
| Q3 | 连续通信约束下运输与中继无人机联合调度 | Q1、Q2 | `projects/q3_joint_relay/outputs/` |
| Q4 | 基于 Q3 的 2 组/3 组分区与资源核算 | Q3 | `projects/q4_partitioning/outputs/` |

依赖关系：`Q1 → Q2 → Q3 → Q4`。各项目通过 `schemas/` 中约定的 CSV/JSON 接口交换结果，不直接读取其他项目的临时文件。

## 目录

```text
data/raw/                  官方原始数据，只读
data/processed/            统一清洗后的可复现数据
src/common/                坐标、DEM、能耗、通信和调度公共逻辑
projects/q1_...q4_/        四个可独立开发和验证的子项目
schemas/                   跨项目输入输出契约
results/submission/        官方提交模板与最终提交文件
paper/                     论文正文与图表
docs/                      赛题和协作文档
scripts/run_pipeline.py    按依赖顺序运行所有已实现子项目
tests/                     公共回归测试
```

## 快速开始

环境要求：Python 3.11 或更高版本。

```powershell
python scripts/run_pipeline.py --list
python scripts/run_pipeline.py --from q1 --to q4
```

每个子项目实现 `projects/<项目>/run.py` 后，会被流水线自动发现。单独运行某一问时，可直接执行该目录下的 `run.py`。

## 协作约定

1. 原始附件只放在 `data/raw/`，分析程序不得原地修改。
2. 公共规则放在 `src/common/`，各问的目标函数、约束和求解器逻辑留在对应项目。
3. 生成数据先写入本项目 `outputs/`，稳定的跨项目结果再按 `schemas/` 契约导出。
4. 一个任务/分支只负责一个明确问题，建议使用 `q1/*`、`q2/*`、`q3/*`、`q4/*` 或 `common/*` 分支名。
5. 合并前至少验证输入字段、单位、坐标系、随机种子和提交模板列顺序。

## 数据说明

- 表格数据：调度中心与服务区、通信链路参数、物资需求与配送时限、运输无人机、中继无人机。
- 地理数据：镇龙乡及周边村镇、水系、水体、道路与 30 m DEM，包含 CSV/MAT/TIF 及说明文件。
- 最终结果必须回填 `results/submission/结果提交模板.xlsx` 的六个工作表。


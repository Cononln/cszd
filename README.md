# cszd

山区洪涝灾害下无人机运输与通信协同优化（数学建模 D 题）的协同建模仓库。

仓库当前为私有仓库。这里只保留赛题、官方数据、提交模板及本队生成的代码与结果；付费资料、内部资料和其他项目的 Git 历史不纳入版本控制。

## 当前进度

| 子项目 | 任务 | 上游依赖 | 标准输出位置 |
| --- | --- | --- | --- |
| Q1-1 | 基础物理模型审查 | 官方数据与 DEM | `implementation/q1/results/` |
| Q1-2 | 最大安全载荷（待确认后运行） | Q1-1 | `implementation/q1/results/` |
| Q1-3/Q1-5 | 组批、敏感性、出图与验证 | Q1-2 | 待进入 |
| Q2-A/B | 供体审计、约束登记与多点路线物理 | Q1 | `implementation/q2/results/` |
| Q2-C–E | UAV/电池调度、Formal ALNS、独立验收 | Q1/Q2-B | `implementation/q2/results/` |
| Q3–Q4 | 暂不修改核心求解 | Q1/Q2 | 待 Q2 冻结后进入 |

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
implementation/q1/         Q1 逐问验收代码与结果
implementation/q2/         Q2-A/B 唯一正式骨架与路线审计结果
tests/                     公共回归测试
```

## 当前正式实现

旧的 A/raw 与 B/super 两套上传代码已经清理。当前正式验收目录包括：

- `implementation/q1/code/common/`：Q1 所需的数据、DEM、航段和能耗公共物理层；
- `implementation/q1/code/q1/audit_physics.py`：Phase Q1-1 基础物理审查；
- `implementation/q1/results/`：审查报告、航段参数和能耗检查结果。
- `implementation/q2/`：Q2-A/B 唯一正式骨架、供体审计和路线物理验收。

Q1 已完成此前阶段验收。Q2-A/B 已通过路线物理审计，Q2-C–E 已完成资源解码、
Formal ALNS 和独立重放验收；`implementation/q2/results/q2_final.json` 是 Q2
冻结状态。Q3/Q4 核心代码未修改。

## 快速开始

环境要求：Python 3.11 或更高版本。

```powershell
python implementation/q1/code/q1/audit_physics.py
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

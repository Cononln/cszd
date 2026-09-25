# Q4 Problem Audit

- status: **PASS**
- source: docs/题目-山区洪涝灾害下无人机运输与通信协同优化.docx，问题四（原文第 24–27 段）

## Original Q4 requirement

以问题三得到的联合调度方案为基础，将15个服务区分别划分为2个和3个任务组；每个服务区恰好归属一个非空任务组，同一运输架次涉及的多个服务区必须同组。保持问题三的货箱组批、服务区访问顺序、运输与中继任务安排及通信保障关系不变；各组独立执行且资源不跨组调配，核算资源数量、冗余、工作量均衡和相对库存的缺口。

## Frozen Q3 boundary

- Q3 selected transport state and route sequence
- Q3 transport schedule and actual UAV/battery assignments
- Q3 relay sorties, service windows, locations, energy components and coverage mapping
- Q2/Q3 physical models, fleet rules, energy rules and validators

## Legal Q4 decision variable

| Variable | Meaning | Domain | Unit | Source clause |
|---|---|---|---|---|
| z_gc | 服务区耦合组件 c 是否属于任务组 g | {0,1} | binary | 问题四：每个服务区必须且只能属于一个任务组；同一运输架次多服务区同组 |

## Ambiguities resolved before modelling

- **题目未指定2组或3组分区的唯一标量目标。** 对每个组数分别报告；代表方案按资源缺口、配置规模、工作量不均衡、稳定状态签名的预先字典序确定。
- **一个冻结中继架次可能覆盖不同任务组的运输需求。** 保持原服务时间、位置和需求—中继关系不变；各组按自身需求复制该冻结服务的资源配置需求，复制仅用于独立库存核算，不反向改写Q3。
- **库存不足是否使分区不可行。** 原题要求报告缺口而未将其禁止；库存短缺作为输出指标，不作为硬不可行约束。

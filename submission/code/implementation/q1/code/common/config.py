# -*- coding: utf-8 -*-
"""全局路径与物理常量配置。

所有求解脚本共用同一套常量，保证"公共物理规则、单位、对象编号和计算口径"
在全文中保持一致（题目第四部分要求）。
"""
from pathlib import Path

# ---------------------------------------------------------------- 路径
PROJ = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJ.parents[1]
DATA = REPO_ROOT / "data" / "raw"
BASE_DATA = DATA / "tabular" / "无人机应急物资运输基础数据"
GEO_DATA = DATA / "geo" / "镇龙乡地理空间数据" / "镇龙乡及周边地理数据"
DEM_TIF = GEO_DATA / "数字高程模型数据（DEM）" / "镇龙乡及周边30米DEM.tif"
VILLAGE_CSV = GEO_DATA / "村镇点位" / "镇龙乡及周边村镇点位.csv"
WATER_POLY_CSV = GEO_DATA / "水体（面）" / "镇龙乡及周边水体.csv"
WATER_LINE_CSV = GEO_DATA / "水系（线）" / "镇龙乡及周边水系.csv"
ROAD_CSV = GEO_DATA / "道路" / "镇龙乡及周边道路.csv"

FIG = PROJ / "figures"
RES = PROJ / "results"
FIG.mkdir(exist_ok=True)
RES.mkdir(exist_ok=True)

# ---------------------------------------------------------------- 物理常量
G = 9.8                     # 重力加速度 m/s^2
KWH_J = 3.6e6               # 1 kWh = 3.6e6 J
CRUISE_CLEARANCE = 50.0     # 计划巡航海拔 = 航段沿途 DEM 最高地面高程 + 50 m
OPS_HEIGHT_O01 = 0.0        # O01 作业高度 = 地面海拔 + 0
OPS_HEIGHT_S = 30.0         # 服务区作业高度 = 地面海拔 + 30 m
GATEWAY_ANT_HEIGHT = 20.0   # 固定网关 G01 天线离地高度 m
RELAY_MAX_HOVER_AGL = 300.0 # 中继最大悬停离地高度 m

# 地球近似（用于经纬度 -> 米）
DEG_LAT_M = 110574.0
DEG_LON_M_EQUATOR = 111320.0

# ---------------------------------------------------------------- 通信常量
CARRIER_MHZ = 2400.0
L_SYS = 3.0                 # 系统损耗 dB
L_OBS = 10.0                # 地形遮挡附加损耗 dB
P_SENS = -98.0              # 接收灵敏度 dBm
FADE_MARGIN = 8.0           # 衰落裕量 dB
P_TH = P_SENS + FADE_MARGIN # 有效接收门限 dBm

# 各通信主体的 (发射功率 dBm, 天线增益 dBi)
TX = {
    "U":   (20.0, 3.0),     # 运输无人机
    "RA":  (20.0, 6.0),     # 中继接入端（对运输无人机）
    "RB":  (19.0, 8.0),     # 中继回传端（对 G01）
    "G01": (27.0, 12.0),    # 固定网关
}

# ---------------------------------------------------------------- 数值口径
EPS = 1e-9

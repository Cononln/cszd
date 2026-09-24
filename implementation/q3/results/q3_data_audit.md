# Q3-A 官方附件数据审计

- status: **PASS**
- relay source: `D:\Users\29919\Documents\科研\cszd\data\raw\tabular\无人机应急物资运输基础数据\中继无人机数据.xlsx`
- communication source: `D:\Users\29919\Documents\科研\cszd\data\raw\tabular\无人机应急物资运输基础数据\通信链路参数.xlsx`
- DEM source: `D:\Users\29919\Documents\科研\cszd\data\raw\geo\镇龙乡地理空间数据\镇龙乡及周边地理数据\数字高程模型数据（DEM）\镇龙乡及周边30米DEM.tif`

## Relay fleet and energy components

{
  "type": {
    "code": "R",
    "name": "中继标准测试多旋翼",
    "m_empty_kg": 21.0,
    "m_comm_kg": 2.5,
    "m_takeoff_kg": 23.5,
    "cruise_speed_mps": 15.0,
    "cruise_power_kw": 1.15,
    "Euse_kwh": 3.2,
    "reserve_rho": 0.2,
    "prep_time_s": 180.0,
    "link_setup_s": 30.0,
    "turnaround_s": 300.0,
    "climb_speed_mps": 4.0,
    "descent_speed_mps": 3.0,
    "climb_efficiency": 0.72,
    "descent_efficiency": 0.0,
    "hover_power_kw": 1.05,
    "communication_power_kw": 0.05,
    "max_hover_agl_m": 300.0,
    "source": "D:\\Users\\29919\\Documents\\科研\\cszd\\data\\raw\\tabular\\无人机应急物资运输基础数据\\中继无人机数据.xlsx",
    "energy_t_full_s": 1800.0
  },
  "fleet": [
    {
      "rid": "R01",
      "rtype": "R",
      "home": "O01"
    },
    {
      "rid": "R02",
      "rtype": "R",
      "home": "O01"
    }
  ],
  "count": 2,
  "energy_components": {
    "rtype": "R",
    "count": 6,
    "t_full_s": 1800.0,
    "source": "D:\\Users\\29919\\Documents\\科研\\cszd\\data\\raw\\tabular\\无人机应急物资运输基础数据\\中继无人机数据.xlsx"
  }
}

## Communication interfaces

{
  "frequency_mhz": 2400.0,
  "system_loss_db": 3.0,
  "obstruction_loss_db": 10.0,
  "receiver_sensitivity_dbm": -98.0,
  "fade_margin_db": 8.0,
  "gateway_antenna_height_m": 20.0,
  "threshold_dbm": -90.0,
  "interfaces": {
    "U": {
      "Pt_dBm": 20.0,
      "Gt_dBi": 3.0
    },
    "RA": {
      "Pt_dBm": 20.0,
      "Gt_dBi": 6.0
    },
    "RB": {
      "Pt_dBm": 19.0,
      "Gt_dBi": 8.0
    },
    "G01": {
      "Pt_dBm": 27.0,
      "Gt_dBi": 12.0
    }
  },
  "source": "D:\\Users\\29919\\Documents\\科研\\cszd\\data\\raw\\tabular\\无人机应急物资运输基础数据\\通信链路参数.xlsx",
  "raw_pt_subjects": [
    "运输无人机",
    "中继接入端",
    "中继回传端",
    "固定网关 G01"
  ]
}

All values are read from the official Excel attachments at runtime; no attachment value is hard-coded.

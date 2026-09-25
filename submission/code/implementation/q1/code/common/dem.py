# -*- coding: utf-8 -*-
"""30 m DEM 读写、航段沿途最高地面高程、三维视线遮挡判定。

关键口径（对应附录 2、附录 3）：
  * 计划巡航海拔 = 航段所经过 DEM 像元的最高地面高程 + 50 m；
  * 地形遮挡判定 = 两端点三维视线连线是否被沿途地形切断。
"""
from __future__ import annotations

import functools
import numpy as np
import rasterio

from .config import DEM_TIF, DEG_LAT_M, DEG_LON_M_EQUATOR


class DEM:
    """轻量 DEM 封装：最近邻取样 + 沿直线剖面采样。"""

    def __init__(self, path=DEM_TIF):
        with rasterio.open(path) as src:
            self.arr = src.read(1).astype(np.float64)
            self.t = src.transform
            self.bounds = src.bounds
            self.nodata = src.nodata
            self.ny, self.nx = self.arr.shape
        if self.nodata is not None:
            self.arr = np.where(self.arr == self.nodata, np.nan, self.arr)
        # 用中位数填充可能的空洞，避免影响最高高程统计
        if np.isnan(self.arr).any():
            self.arr = np.where(np.isnan(self.arr), np.nanmedian(self.arr), self.arr)

    # -------------------------------------------------------------- 索引
    def rc(self, lon, lat):
        """经纬度 -> (row, col) 浮点索引。"""
        col = (np.asarray(lon) - self.t.c) / self.t.a
        row = (np.asarray(lat) - self.t.f) / self.t.e
        return row, col

    def elev(self, lon, lat):
        """最近邻取样高程（m）。越界返回 NaN。"""
        row, col = self.rc(lon, lat)
        r = np.round(row).astype(int)
        c = np.round(col).astype(int)
        inside = (r >= 0) & (r < self.ny) & (c >= 0) & (c < self.nx)
        out = np.full(np.shape(r), np.nan)
        if np.ndim(r) == 0:
            return float(self.arr[r, c]) if inside else np.nan
        out[inside] = self.arr[r[inside], c[inside]]
        return out

    def in_bounds(self, lon, lat):
        return (self.bounds.left <= lon <= self.bounds.right and
                self.bounds.bottom <= lat <= self.bounds.top)

    # -------------------------------------------------------------- 剖面
    def profile(self, lon0, lat0, lon1, lat1, step_m=15.0):
        """沿直线采样。

        返回 (s, lon_s, lat_s, elev_s)：s 为累计水平距离(m)。
        """
        mlat = (lat0 + lat1) / 2.0
        dx = (lon1 - lon0) * DEG_LON_M_EQUATOR * np.cos(np.radians(mlat))
        dy = (lat1 - lat0) * DEG_LAT_M
        dist = float(np.hypot(dx, dy))
        n = max(int(np.ceil(dist / step_m)) + 1, 2)
        t = np.linspace(0.0, 1.0, n)
        lon_s = lon0 + (lon1 - lon0) * t
        lat_s = lat0 + (lat1 - lat0) * t
        e = self.elev(lon_s, lat_s)
        return t * dist, lon_s, lat_s, e

    def max_elev_path(self, lon0, lat0, lon1, lat1, step_m=15.0):
        """航段沿途 DEM 像元最高地面高程（m）。"""
        _, _, _, e = self.profile(lon0, lat0, lon1, lat1, step_m)
        e = e[~np.isnan(e)]
        return float(e.max()) if e.size else np.nan

    # -------------------------------------------------------------- 视线
    def los_blocked(self, p0, p1, step_m=10.0, clearance=0.0):
        """三维视线遮挡判定。

        p0, p1 = (lon, lat, alt_m)。返回 True 表示存在地形遮挡。
        判定：沿线任一点的地面高程高于视线插值高度（+clearance）即为遮挡。
        端点自身所在像元的前若干米跳过，避免把天线脚下地面误判为遮挡。
        """
        lon0, lat0, z0 = p0
        lon1, lat1, z1 = p1
        s, lon_s, lat_s, e = self.profile(lon0, lat0, lon1, lat1, step_m)
        total = s[-1]
        if total < 1e-6:
            return False
        # 跳过两端各 1 个像元（约 30 m）的缓冲区
        skip = 30.0
        m = (s > skip) & (s < total - skip)
        if not m.any():
            return False
        s_m, e_m = s[m], e[m]
        z_line = z0 + (z1 - z0) * (s_m / total)
        return bool(np.any(e_m > z_line + clearance))


@functools.lru_cache(maxsize=1)
def get_dem() -> DEM:
    return DEM()


@functools.lru_cache(maxsize=1)
def dem_stats() -> dict:
    d = get_dem()
    return dict(shape=d.arr.shape, res_deg=d.t.a,
                lon=(d.bounds.left, d.bounds.right),
                lat=(d.bounds.bottom, d.bounds.top),
                zmin=float(np.nanmin(d.arr)), zmax=float(np.nanmax(d.arr)),
                zmean=float(np.nanmean(d.arr)),
                zmedian=float(np.nanmedian(d.arr)))


def haversine_m(lon0, lat0, lon1, lat1):
    """两点水平大圆距离（m）。"""
    R = 6371008.8
    p0, p1 = np.radians(lat0), np.radians(lat1)
    dp = p1 - p0
    dl = np.radians(lon1 - lon0)
    a = np.sin(dp / 2) ** 2 + np.cos(p0) * np.cos(p1) * np.sin(dl / 2) ** 2
    return float(2 * R * np.arcsin(np.sqrt(a)))


def planar_m(lon0, lat0, lon1, lat1):
    """局部平面近似距离（m），与题目"水平直线"口径一致。"""
    mlat = (lat0 + lat1) / 2.0
    dx = (lon1 - lon0) * DEG_LON_M_EQUATOR * np.cos(np.radians(mlat))
    dy = (lat1 - lat0) * DEG_LAT_M
    return float(np.hypot(dx, dy))


if __name__ == "__main__":
    import json
    from .data import load_nodes
    d = get_dem()
    print(json.dumps(dem_stats(), ensure_ascii=False, indent=1))
    n = load_nodes().set_index("id")
    print("O01 处 DEM 高程 = %.1f m（表格海拔 %.1f m）" %
          (d.elev(n.loc["O01", "lon"], n.loc["O01", "lat"]), n.loc["O01", "elev"]))
    for s in ["S001", "S015", "S010"]:
        r = n.loc[s]
        print("%s DEM=%.1f 表格=%.1f  到O01距离=%.0f m 沿途最高=%.1f m" % (
            s, d.elev(r.lon, r.lat), r.elev,
            planar_m(n.loc["O01", "lon"], n.loc["O01", "lat"], r.lon, r.lat),
            d.max_elev_path(n.loc["O01", "lon"], n.loc["O01", "lat"], r.lon, r.lat)))

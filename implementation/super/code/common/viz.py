# -*- coding: utf-8 -*-
"""通用高级图表构件：桑基流向图、雷达图、帕累托前沿、甘特条。

matplotlib 没有可用的桑基图原语（``matplotlib.sankey`` 画的是单流管道图），
plotly 的桑基图又只能导出 HTML，故这里用三次贝塞尔缎带手绘，
保证与全文其余插图在字体、配色、DPI 上完全一致。
"""
from __future__ import annotations

import numpy as np
from matplotlib.path import Path as MPath
from matplotlib.patches import PathPatch, Rectangle


# --------------------------------------------------------------- 桑基流向图
def _ribbon(ax, x0, x1, y0a, y0b, y1a, y1b, color, alpha=0.42):
    """(x0, y0a..y0b) 到 (x1, y1a..y1b) 的缎带。"""
    xm = 0.5 * (x0 + x1)
    verts = [
        (x0, y0a), (xm, y0a), (xm, y1a), (x1, y1a),
        (x1, y1b), (xm, y1b), (xm, y0b), (x0, y0b), (x0, y0a),
    ]
    codes = [MPath.MOVETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4,
             MPath.LINETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4,
             MPath.CLOSEPOLY]
    ax.add_patch(PathPatch(MPath(verts, codes), facecolor=color,
                           edgecolor="none", alpha=alpha, zorder=2))


def sankey(ax, left, right, flows, node_w=0.055, gap=0.022,
           left_x=0.06, right_x=0.94, alpha=0.42, label_fs=8.6,
           flow_label=True, value_fmt="{:.1f}"):
    """双侧桑基图。

    left / right : ``[(label, value, color), ...]``，按给定顺序自上而下排布
    flows        : ``[(i, j, value, color), ...]``，i/j 为左右结点下标
    """
    def layout(nodes):
        tot = sum(v for _, v, _ in nodes) or 1.0
        span = 1.0 - gap * max(len(nodes) - 1, 0)
        pos, y = [], 1.0
        for _, v, _ in nodes:
            h = span * v / tot
            pos.append([y - h, y])          # [bottom, top]
            y -= h + gap
        return pos

    pl, pr = layout(left), layout(right)
    cur_l = [p[1] for p in pl]
    cur_r = [p[1] for p in pr]

    # 缎带：按流量降序绘制，小的压在上面不被盖住
    for i, j, v, c in sorted(flows, key=lambda z: -z[2]):
        hl = (pl[i][1] - pl[i][0]) * v / (sum(x[1] for x in left) or 1)
        hr = (pr[j][1] - pr[j][0]) * v / (sum(x[1] for x in right) or 1)
        _ribbon(ax, left_x + node_w, right_x, cur_l[i] - hl, cur_l[i],
                cur_r[j] - hr, cur_r[j], c, alpha)
        if flow_label and v > 0:
            # 标签贴在缎带的抵达端：同一右结点各条入流在纵向恰好平铺它的
            # 高度，因此标签天然互不重叠（放在中点则会在交叉处糊成一团）。
            ax.text(right_x - 0.012, cur_r[j] - 0.5 * hr,
                    value_fmt.format(v), ha="right", va="center",
                    fontsize=7.2, color="#333333", zorder=6,
                    bbox=dict(boxstyle="round,pad=0.12", fc="white",
                              ec="none", alpha=0.72))
        cur_l[i] -= hl
        cur_r[j] -= hr

    for x, pos, nodes, ha, tx in ((left_x, pl, left, "right", left_x - 0.012),
                                  (right_x, pr, right, "left", right_x + node_w + 0.012)):
        for (lab, v, c), (b, t) in zip(nodes, pos):
            ax.add_patch(Rectangle((x, b), node_w, t - b, facecolor=c,
                                   edgecolor="none", zorder=3))
            ax.text(tx, 0.5 * (b + t), f"{lab}  {value_fmt.format(v)}",
                    ha=ha, va="center", fontsize=label_fs, zorder=4)
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.03, 1.03)
    ax.axis("off")


# ------------------------------------------------------------------- 雷达图
def radar(ax, labels, series, colors, rmax=None, fill_alpha=0.16,
          label_fs=8.8, tick_fs=7.6):
    """多指标雷达图。series: ``[(name, values), ...]``（values 已归一化到 [0,1]）。"""
    n = len(labels)
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ang_c = np.concatenate([ang, ang[:1]])
    for (name, vals), c in zip(series, colors):
        v = np.concatenate([np.asarray(vals, dtype=float), [vals[0]]])
        ax.plot(ang_c, v, color=c, lw=1.9, label=name, zorder=3)
        ax.fill(ang_c, v, color=c, alpha=fill_alpha, zorder=2)
    ax.set_xticks(ang)
    ax.set_xticklabels(labels, fontsize=label_fs)
    ax.set_ylim(0, rmax if rmax else 1.02)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels([f"{t:.2g}" for t in (0.25, 0.5, 0.75, 1.0)],
                       fontsize=tick_fs, color="#777777")
    ax.grid(color="#D9D9D9", lw=0.7)
    ax.set_axisbelow(True)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(pad=1)


# ------------------------------------------------------------- 帕累托前沿
def pareto_mask(x, y):
    """返回 (x, y) 点集里非支配点（x 越小越好、y 越小越好）的布尔掩码。"""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    keep = np.ones(n, bool)
    for i in range(n):
        if keep[i]:
            dominated = (x <= x[i]) & (y <= y[i]) & ((x < x[i]) | (y < y[i]))
            if dominated.any():
                keep[i] = False
    return keep


# ------------------------------------------------------------------- 甘特图
def gantt_rows(ax, rows, t0_key="start", t1_key="end",
               color_key="color", label_key="label", height=0.56,
               edge="#FFFFFF"):
    """横向甘特条。rows: ``[{...}, ...]``。"""
    for k, r in enumerate(rows):
        s, e = r[t0_key], r[t1_key]
        ax.barh(k, e - s, left=s, height=height, color=r[color_key],
                edgecolor=edge, linewidth=0.7, zorder=3)

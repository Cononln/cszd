# -*- coding: utf-8 -*-
"""全文统一的绘图样式：SimSun 中文字体、统一配色、统一导出规格。

所有作图脚本一律 `from common.style import *`，保证整篇论文的图表在字体、
配色、线宽、DPI 上完全一致。
"""
from __future__ import annotations

import logging
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import seaborn as sns
from matplotlib import rcParams

warnings.filterwarnings("ignore")


class _QuietFontWeight(logging.Filter):
    """SimSun 只有 Regular 字面，请求 bold 时 matplotlib 会回退成 400。

    这是预期行为（中文粗体由排版而非字重承担），但每次进程都会刷一行
    findfont 警告，故定点静音，其余字体警告仍然放行。
    """

    def filter(self, record):
        return "Failed to find font weight" not in record.getMessage()


logging.getLogger("matplotlib.font_manager").addFilter(_QuietFontWeight())

FIGDIR = Path(__file__).resolve().parents[2] / "figures"
FIGDIR.mkdir(exist_ok=True)
DPI = 300

# ------------------------------------------------------------------ 字体
# 论文要求中文使用 SimSun；正文/标签用宋体，数学与数字用 Times New Roman。
_SIMSUN = None
for _p in (r"C:\Windows\Fonts\simsun.ttc", r"C:\Windows\Fonts\SimSun.ttf"):
    if Path(_p).exists():
        fm.fontManager.addfont(_p)
        _SIMSUN = fm.FontProperties(fname=_p).get_name()
        break
if _SIMSUN is None:
    _SIMSUN = "SimSun"

_RC = {
    "font.family": "sans-serif",
    "font.sans-serif": [_SIMSUN, "SimSun", "Times New Roman", "DejaVu Sans"],
    # 含 $...$ 的字符串会整体走 mathtext，若其字体不含中文就会出现方框；
    # 故把 mathtext 的各个字面统一指向 SimSun，并保留 STIX 作为缺字符回退。
    "mathtext.fontset": "custom",
    "mathtext.rm": _SIMSUN,
    "mathtext.it": _SIMSUN,
    "mathtext.bf": _SIMSUN,
    "mathtext.sf": _SIMSUN,
    "mathtext.cal": _SIMSUN,
    "mathtext.fallback": "stix",
    "font.size": 10.5,
    "axes.unicode_minus": False,        # 负号正常显示，避免方框
    "axes.titlesize": 11.5,
    "axes.labelsize": 10.5,
    "axes.linewidth": 0.9,
    "axes.edgecolor": "#333333",
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": "#D9D9D9",
    "grid.linewidth": 0.6,
    "grid.alpha": 0.8,
    "xtick.labelsize": 9.5,
    "ytick.labelsize": 9.5,
    "xtick.direction": "out",
    "ytick.direction": "out",
    "legend.fontsize": 9.5,
    "legend.frameon": True,
    "legend.framealpha": 0.92,
    "legend.edgecolor": "#BFBFBF",
    "lines.linewidth": 1.8,
    "lines.markersize": 5.5,
    "figure.dpi": 120,
    "savefig.dpi": DPI,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.06,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
}
rcParams.update(_RC)

# ------------------------------------------------------------------ 配色
# 机型三色的语义在全文中固定不变：A 蓝 / B 橙 / C 绿
GCOLOR = {"A": "#4C72B0", "B": "#DD8452", "C": "#55A868"}
GNAME = {"A": "A 型", "B": "B 型", "C": "C 型"}
# 语义色板：直连 / 中继 / 中断
MODE_COLOR = {"直连": "#4C72B0", "中继": "#DD8452", "中断": "#C44E52"}
PHASE_COLOR = {"爬升": "#8172B3", "巡航": "#4C72B0",
               "下降": "#937860", "投送": "#55A868"}
PALETTE = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3",
           "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD"]
SEQ = "viridis"
DIV = "RdBu_r"


def apply_theme():
    """统一底色主题（seaborn 层面）。

    注意：``sns.set_theme`` 会用自带默认值覆盖 ``font.sans-serif``
    （SimSun 被换成 Arial/DejaVu），导致中文与含 ``$...$`` 的混排字符串
    大面积缺字形。因此必须在它之后再回灌一遍本文的 ``_RC``。
    """
    sns.set_theme(style="ticks")
    rcParams.update(_RC)


def despine(ax, keep=("left", "bottom")):
    sns.despine(ax=ax, top="top" not in keep, right="right" not in keep)


def save(fig, name, tight=True):
    """保存到 figures/<name>.png 并返回路径。"""
    p = FIGDIR / f"{name}.png"
    if tight:
        fig.tight_layout()
    fig.savefig(p, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  saved", p.name)
    return p


def tag(ax, text, dx=0.02, dy=0.97, **kw):
    """子图角标 (a)/(b)…

    角标是纯 ASCII，用 DejaVu Sans 取真粗体；SimSun 无 bold 字面，
    走 SimSun 会触发 "Failed to find font weight bold" 回退。
    """
    kw.setdefault("fontsize", 11)
    kw.setdefault("fontweight", "bold")
    kw.setdefault("fontfamily", "DejaVu Sans")
    ax.text(dx, dy, text, transform=ax.transAxes,
            va="top", ha="left", **kw)

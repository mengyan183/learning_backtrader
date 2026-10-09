# -*- coding: utf-8 -*-
"""守猪待兔图表数字化（第 12.26 条）。

================================================================================
⚠️ 状态：**部分成功，y 轴标定未收敛 —— 输出不得用于仓位决策**
================================================================================
已验证可用：
  - 颜色分离干净：贪恐指数 = 紫 `(124,58,237)`，股价 = 蓝 `(37,99,235)`
  - 曲线逐列提取可用（每列取紫色像素的 y 均值）

**未解决**：y 轴的「像素 → 指数值」标定。两种尝试都不成立：
  1. 假设绘图区线性映射到 ±90：
     `≤0` 复现 69.9%（官方 70.8%）✓ 中段吻合，
     但 `≤−80` 复现 16.9%（官方 29.6%）✗、末值 40.9（官方 24）✗。
  2. 用官方 9 个分位点反解线性标定：残差 RMS **15.70**，反推的 y 轴范围
     `y=41 → −238`、`y=204 → +53`，**不合理** ⇒ 拟合失败。

**最可能的原因**：图表 y 轴上限是 **±90**，而守猪待兔量程是 **±100**
⇒ 曲线在极端处被**裁剪**（这正好解释 `≤−80` 被低估）。
但裁剪**不能**解释末值 40.9 vs 24 的偏差，说明还有别的因素（轴非线性、
或我对轴标签的读取有误）。**在查清之前不输出可用数据。**

**因此本脚本目前只做一件事**：把提取到的**原始 y 序列**落盘（这部分是可靠的），
供标定问题解决后直接复用，不必重新提取。
"""
import os

import numpy as np
import pandas as pd
from PIL import Image

from fg_system import config

# 每张图的绘图区与日期范围（从图上读出）。y0/y1 是**像素**边界。
CHARTS = {
    "CONL": {"file": "CONL.png", "start": "2024-08-16", "end": "2026-09-22",
             "x0": 44, "x1": 1036, "y0": 41, "y1": 204},
    "YINN": {"file": "YINN.png", "start": "2024-04-23", "end": "2026-09-22",
             "x0": 44, "x1": 1036, "y0": 41, "y1": 204},
    "GDXU": {"file": "GDXU.png", "start": "2024-08-24", "end": "2026-09-22",
             "x0": 44, "x1": 1036, "y0": 41, "y1": 204},
}

# 官方历史分布（用户从 App 抄录，作为**校验用**的独立事实，不参与标定）
OFFICIAL = {
    "CONL": {0: 70.8, -60: 38.4, -80: 29.6, 60: 7.9, 80: 4.3, "days": 541},
    "YINN": {0: 46.9, -60: 5.1, -80: 0.0, 60: 16.2, 80: 5.9, "days": 623},
    "GDXU": {0: 41.6, -60: 18.1, -80: 13.4, 60: 38.8, 80: 28.6, "days": 580},
}


def extract_raw_y(path, x0, x1, y0, y1):
    """逐列提取紫色曲线的 y（像素），返回 Series（index = 列号）。

    只返回**原始像素**，不做任何数值标定 —— 标定未解决（见模块 docstring）。
    """
    a = np.asarray(Image.open(path).convert("RGB")).astype(int)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    purple = (b > 150) & (b - g > 60) & (r - g > 20)
    purple[:y0, :] = False          # 去掉图例区（图例在绘图区之上）
    purple[y1:, :] = False
    xs, ys = [], []
    for x in range(x0, x1 + 1):
        col = np.where(purple[:, x])[0]
        if len(col):
            xs.append(x)
            ys.append(float(col.mean()))
    return pd.Series(ys, index=xs, name="y_px")


def main():
    out_dir = os.path.join(config.DATA_DIR, "shoutu_digitized")
    os.makedirs(out_dir, exist_ok=True)
    print("=" * 92)
    print("守猪待兔图表数字化 —— ⚠️ y 轴标定未收敛，以下仅供诊断，**不得用于仓位决策**")
    print("=" * 92)
    for sym, cfg in CHARTS.items():
        path = os.path.join(config.DATA_DIR, "raw", "shoutu_charts", cfg["file"])
        if not os.path.exists(path):
            print("%-6s 缺文件 %s" % (sym, path))
            continue
        s = extract_raw_y(path, cfg["x0"], cfg["x1"], cfg["y0"], cfg["y1"])
        dst = os.path.join(out_dir, "%s_raw_y.csv" % sym)
        s.rename("y_px").to_csv(dst, header=True, index_label="x_px")
        # 仅供诊断的**未标定**映射（假设 ±90）
        v = 90.0 + (s - cfg["y0"]) / (cfg["y1"] - cfg["y0"]) * (-180.0)
        off = OFFICIAL[sym]
        print()
        print("%s  列数 %d  y_px %.1f~%.1f   ->  %s"
              % (sym, len(s), s.min(), s.max(), os.path.relpath(dst, config.ROOT)))
        print("   诊断（假设 ±90，**未验证**）：")
        for th in (-80, -60, 0, 60, 80):
            print("      ≤%+4d  复现 %5.1f%%   官方 %5.1f%%   差 %+5.1f"
                  % (th, (v <= th).mean() * 100, off[th], (v <= th).mean() * 100 - off[th]))
        print("      末值 %+.1f（官方 %.0f）" % (v.iloc[-1], off[0] * 0 + 24 if sym == "CONL" else float("nan")))
    print()
    print("原始 y 序列已落盘（这部分可靠）；标定问题解决后可直接复用，无需重新提取。")


if __name__ == "__main__":
    main()

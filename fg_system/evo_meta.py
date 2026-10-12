# -*- coding: utf-8 -*-
"""进化研究产物元数据读取（WT-18：OOS 起点单一来源）。

**背景**：仓库里存在**两类语义不同**的 OOS 起点，切勿强行合并：

1. **纪律声明口径** —— `fg_system.config.OOS_START`（与 `IS_START/IS_END` 配对）。
   这是**先验固定的生产样本外边界**，注释「禁止调参」，
   语义是「这条线之后的数据只能验收一次」。
2. **研究产物口径** —— `evolution/baseline.json` 的
   `meta.is_oos.oos_start`，由 `scripts/evolve_baseline.py::_split_is_oos`
   对实际收益序列做**时间序 80/20 切分**实测得出。

二者的**数字不同是正常的**（一个是纪律，一个是数据派生），但历史上研究脚本
（`evolve_propose.py` / `evolve_variant.py`）各自**硬编码字面日期**
并声称「与 baseline meta 同口径」——那其实是**第三套值**且与 meta 实测差一天。

本模块提供研究脚本的**唯一读取入口**：直接读 `baseline.json` 的实测值，
消除硬编码与 off-by-one。生产纪律仍以 `config.OOS_START` 为准。
"""
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_PATH = os.path.join(REPO, "evolution", "baseline.json")


def load_baseline_meta(path=None):
    """读 `evolution/baseline.json` 的 `meta` 段（研究产物，只读）。"""
    with open(path or BASELINE_PATH, encoding="utf-8") as fh:
        return json.load(fh)["meta"]


def oos_start(path=None):
    """研究产物口径的样本外起点（`meta.is_oos.oos_start`）。

    这是**数据派生的 80/20 切分实测值**，供研究脚本（变体/提案）使用；
    与 `config.OOS_START`（纪律声明，先验固定）语义不同，见模块 docstring。
    """
    return load_baseline_meta(path)["is_oos"]["oos_start"]


def is_end(path=None):
    """研究产物口径的样本内终点（`meta.is_oos.is_end`）。"""
    return load_baseline_meta(path)["is_oos"]["is_end"]

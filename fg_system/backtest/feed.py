# -*- coding: utf-8 -*-
"""FgPandasData：把 features.csv 接入 backtrader（§11.1）。"""
import backtrader as bt


class FgPandasData(bt.feeds.PandasData):
    lines = ("fg_index", "zone", "target_position")
    params = (
        ("fg_index", -1),
        ("zone", -1),
        ("target_position", -1),
    )

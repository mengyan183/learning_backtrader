# -*- coding: utf-8 -*-
"""FgStrategy：只读 target_position 下单（§11.2）。

禁止在本类内做任何指标计算或条件判断——所有决策已在 signal 层完成。
本类只做三件事：读目标仓位 → 套执行约束（防抖动阈值 / 单次调整上限）→ 下单。
"""
import backtrader as bt

from fg_system.signal import portfolio


class FgStrategy(bt.Strategy):
    params = (
        ("verbose", False),
    )

    def __init__(self):
        self.order_count = 0
        self.executed_positions = []
        self.current_position = 0.0
        self._pending = False

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            self.executed_positions.append(self.current_position)
        self._pending = False

    def next(self):
        if self._pending:
            return
        target = self.datas[0].target_position[0]

        # **唯一实现**在 signal 层：`portfolio.next_position`。
        # 分析脚本（scripts/analyze_shoutu_greed.py）调的是**同一个函数** ⇒
        # "分析里的规则 = 回测里的规则"是**构造保证**，不靠测试去证明等价。
        adjusted = portfolio.next_position(self.current_position, target)
        if adjusted == self.current_position:
            return

        self.order_count += 1
        self._pending = True
        self.current_position = adjusted
        self.order_target_percent(target=adjusted)

    def stop(self):
        self.executed_positions.append(self.current_position)

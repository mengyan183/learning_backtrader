# -*- coding: utf-8 -*-
"""`run_script` 白名单标记：允许跑 `scripts/weight_compare.py` ✓。

为什么放行（2026-11-20）：第 12.47 条把波动率族权重从 40.5% 降到 30%，
**回测未重跑** ⇒ 需要先看清「信号本身变了多少」才能判断要不要接受 ✓

⚠️ 该脚本 `pipeline.run(write=False)` ⇒ **不写任何文件** ✓
   只打印统计（fg_index 分布 / 五档占比 / 换手 / IC）✗
"""

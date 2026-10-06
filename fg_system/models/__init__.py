# -*- coding: utf-8 -*-
"""数学模型包（2026-10-06 落地，纯 numpy/pandas，零新依赖）。

与贪恐系统结合点（docs/roadmap.md 数学建模扩展）：
- markov.py      档位转移马尔可夫矩阵：量化"连续下跌/状态延续"概率
- hmm.py         Gaussian HMM（EM+Viterbi）：市场 regime 识别
- evt.py         极值理论 GPD/POT：极端档位阈值校准（20/80 边界合理性）
- bayes_update.py Beta-Bernoulli：H 假说先验→后验自动更新

纪律：全部只读 Data/features.csv 等历史数据，不改策略参数、不经 LLM 判决；
分析结果写入 Data/model_report_*.json 供看板/简报引用。
"""

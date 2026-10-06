---
name: kb-search
description: "Semantic search over the local YouTube trading knowledge base (ChromaDB + Ollama bge-m3, covering 9 channels: Duomo, SecretMindset, TradingChannel, RaynerTeo, ChatWithTraders, PBoyle, BenFelix, ThePlainBagel, QuantPy). Use for trading strategy, risk management, stop-loss/take-profit, trading psychology, position sizing, technical analysis, quant modeling questions. Chinese or English queries both work."
version: 1.0.0
author: xingguo
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [Trading, KnowledgeBase, ChromaDB, RAG, YouTube, RiskManagement]
    related_skills: [fg-qa, futuapi]
---

# YouTube 交易知识库检索

本地向量库语义检索（中查英 / 英查英），覆盖 9 个交易频道字幕，返回最相关视频片段及来源。

## Quick Reference

| Action | Command |
|---|---|
| 中文查询 | `.venv/bin/python scripts/kb_search.py "如何设置止损" -n 3` |
| 英文查询 | `.venv/bin/python scripts/kb_search.py "position sizing" -n 5` |
| 只看来源 | `.venv/bin/python scripts/kb_search.py "leverage risk" --top` |

所有命令在 `/Users/xingguo/learning_backtrader` 目录下执行（仓库 venv 解释器 `.venv/bin/python`）。

## 检索规则

1. 检索结果逐条标注「来源：<频道>《<标题>》（YouTube 知识库，上传日期）」。
2. 知识库内容为**教育观点**，信号分级一律 🟡 研究参考，不替代系统买卖信号。
3. 无命中时直说「知识库未检索到相关内容」，不编造。
4. 引用片段保持原意，不夸大、不断章取义。

## 维护

- 自动更新：`scripts/kb_update.sh`（launchd 每周日 03:00，label com.xingguo.fg-kb-update）
- 手动更新：`scripts/kb_build.py`（幂等）
- 数据：`Data/kb/chroma`（向量库）、`Data/kb/subtitles`（VTT 原文）、`Data/kb/yt_meta.json`（元数据）

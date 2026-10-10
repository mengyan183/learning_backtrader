# llmfit 硬件适配检测报告（MacBook Pro）

> 检测日期：2026-10-10 ｜ 工具：llmfit 1.1.17（本地运行，不上传硬件信息）
> 数据来源：`llmfit system --json` + `llmfit fit --json`（10423 个模型评分）

## 1. 硬件画像

| 项 | 检测值 |
|---|---|
| CPU | Intel Core i9-9880H（16 核，2.3GHz） |
| GPU | AMD Radeon Pro 560X **4GB VRAM**（Metal）+ Intel UHD 630 1.5GB |
| 内存 | 16GB（可用 11.85GB，非统一内存） |
| 平台 | Intel MacBook Pro（2019 款），Metal 后端，llama.cpp 未配置 |

**关键约束**：4GB 独显 + 16GB 内存 → 流畅档为 **3B–8B 量化模型**；14B+ 需低量化+CPU 卸载，体验明显下降。

## 2. 评分分布（10423 模型）

| fit_label | 数量 |
|---|---|
| Perfect | 1764 |
| Good | 2110 |
| Marginal | 4474 |
| Too Tight | 2075 |

## 3. 推荐清单（按用途）

### ✅ 推荐档（GPU 全载，40+ tok/s）
| 模型 | 参数 | 量化 | 体积 | 速度 | 评分 | 用途 |
|---|---|---|---|---|---|---|
| Qwen3.5-4B-SWQ | 3.3B | Q8_0 | 3.4GB | 42.9 | 87.7 | 多模态/视觉 |
| Llama-3.2-3B | 3.2B | Q8_0 | 3.4GB | 43.8 | 87.3 | 聊天 |
| Qwen2.5-Coder-3B(-Instruct) | 3.1B | Q8_0 | 3.2GB | 45.6 | 86.7 | **编程首选** |
| Qwen2.5-3B-Instruct | 3.1B | Q8_0 | 3.2GB | 45.6 | 86.4 | 通用对话 |

### 🟡 可跑档（低量化，28+ tok/s）
| 模型 | 参数 | 量化 | 体积 | 速度 | 评分 |
|---|---|---|---|---|---|
| DeepSeek-R1-Distill-Qwen-7B | 7.8B | Q3_K_M | 3.7GB | 28.4 | 85.6 |
| DeepSeek-R1-0528-Qwen3-8B | 8.2B | Q2_K | 3.0GB | 29.0 | 85.1 |
| Qwen3.5-9B 蒸馏系 | 8–9B | Q3_K_M | ~4GB | 26.8 | 85.9 |

### 🔴 不建议档
- 14B+ 全量：显存放不下，CPU 卸载拖慢
- 27B MoE（Qwen3.5-27B 蒸馏）：CPU+GPU 混合仅 5.4 tok/s
- 8K+ 长上下文：KV Cache 挤占内存

## 4. 结论与命令

本机最适合 **3–4B Q8 全量**（快且稳）；要更强推理可上 **7–8B 低量化**；14B+ 不建议。速度均为估算，实测用 `llama-bench -m <gguf> -ngl 99 -p 512 -n 128`。

```bash
ollama run qwen2.5-coder:3b     # 编程主力
ollama run qwen2.5:3b           # 通用对话
ollama run deepseek-r1:7b       # 更强推理（对应 Distill-Qwen-7B）
```

## 5. 与贪恐系统现状对照

- 主链路（OpenClaw）：`nvidia/deepseek-v4.1-flash` → `zai/glm-4.7-flash` → `ollama/qwen2.5-coder:1.5b`（本地仅兜底）
- 本地已装：qwen2.5-coder:1.5b/3b/3b-64k、internlm2:1.8b（文本）、bge-m3（知识库嵌入）
- **结论：本地无需部署新模型**。主推理走云 API 性能远超本机可跑档位；本地角色 = 兜底 + 嵌入（bge-m3 已满足）；本机无 Apple Silicon 统一内存，跑大模型性价比低。

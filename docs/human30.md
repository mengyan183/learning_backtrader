# Human 3.0 组合骨架

> 2026-10-10 用户拍板：在贪恐系统中新增 Human 3.0 系统。
> 形态 = **组合骨架**（四象限自评 + 每日状态记录 + 简报输出），交付 = **dashboard 新 tab**。
> 框架来源：Dan Koe Human 3.0（四象限 × 三级意识）+ 孙宇晨×邵艾伦访谈行动原则（先开地图/先行动/小自我/AI 自动化）。

## 定位

贪恐系统管"市场"，Human 3.0 管"人"：交易者的认知/身体/精神/事业四象限状态。
骨架期落地**确定性规则**（无 LLM 判决，符合仓库纪律），后续可扩展。

## 四象限（0-100 自评）

| 象限 | 代码 | 含义 |
|---|---|---|
| 心/认知 | mind | 思维、心智模型、认知升级（AI 素养） |
| 体/行动 | body | 健康、健身、执行力（薄肌理论落点） |
| 精神/意义 | spirit | 关系、心态、小自我、生命感 |
| 职/事业 | vocation | 事业、系统、选择权、轻资产 |

## 意识层级判定（可复算规则）

```
avg = 四象限均值（0-100）
avg < 40        → L1 从众者 Conformist（外部权威驱动·社会模板）
40 <= avg <= 70 → L2 个体主义者 Individualist（内部权威驱动·我的方式）
avg > 70        → L3 综合者 Synthesist（多视角整合·策略设计）
std > 20        → 失衡标记（短板象限显著落后）
```

## 建议规则（确定性，无 LLM）

- 短板 < 40：优先补短板（木桶效应，四象限同步升级）
- 短板 40-70：次短板，保持节奏小幅提升
- 全 ≥ 70：已达综合者态 → 外化输出（传承/教学/沉淀系统）
- 失衡（std>20）：提示聚焦短板，勿让短板拖垮整体迁移能力
- 较上次下降 ≥5 的象限：趋势提示
- 固定注入孙学引擎行动原则一行（骨架期仅提示）

## 数据与接入

| 项 | 位置 |
|---|---|
| 核心模块 | `fg_system/human30.py`（record/latest/history/aggregate/advice/brief_line） |
| 打卡 CLI | `scripts/human30_cli.py`（--set/--latest/--history） |
| 数据文件 | `Data/human30.json`（运行态，.gitignore 不入库） |
| 网页面板 | dashboard 第 4 个 tab「Human 3.0」（Level 进度条 + 四象限状态卡 + 快速打卡表单 + 雷达图 + 最近 30 次趋势 + 历史表） |
| 页面打卡端点 | `POST /api/human30`（Flask，0-100 校验，当日覆盖，返回最新记录+聚合） |
| 每日简报 | `build_brief_sections` 新增「🌱 Human 3.0 状态」板块（无记录时跳过） |
| 测试 | `tests/test_human30.py`（level 边界/聚合/建议/记录幂等）＋ `tests/dashboard/test_server.py`（端点写入/校验/当日覆盖） |

## 用法

```bash
# 打卡（当日重复则覆盖）—— CLI 方式
.venv/bin/python scripts/human30_cli.py --set --mind 65 --body 55 --spirit 60 --vocation 50 --note "今日状态"
# 查询
.venv/bin/python scripts/human30_cli.py --latest
# 历史
.venv/bin/python scripts/human30_cli.py --history 30
```

**页面打卡**：dashboard「Human 3.0」tab 底部表单直接打分（心/体/精神/职 0-100 + 备注），
保存后当日覆盖并刷新页面；等价于 CLI `--set`。

## 后续扩展（骨架之外，未落地）

- 与交易行为联动（如极端档位时记录交易者状态 → 归因）
- AI 复盘（用 LLM 生成解读——需单独审批，绕开"无 LLM 判决"纪律需走 C-2/C-3 流程）

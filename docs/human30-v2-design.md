# Human 3.0 忠实版设计（v2 spec）

> 状态：**待审批**（C-2 提案见 `docs/proposals/proposal_H30V2_2026-10-14.md`）
> 提出：2026-10-14 ｜ 修订：2026-10-14（按 4 角色团队评审全修，见 `docs/review/团队评审-2026-10-14-human30v2.md`）
> **依据：原文已获取并精读** ✓（本地 HTML：`human3.0orogintext/`）

## 来源标记约定（评审 S-1/S-2 要求）
| 标记 | 含义 | 文件 |
|---|---|---|
| **〔主文〕** | Dan Koe《HUMAN 3.0 – A Map To Reach The Top 1%》2025-08-26 | `h30orig/main.txt` |
| **〔Prompt〕** | 《Prompt: HUMAN 3.0 Self-Discovery & Metatype Test》2025-08-27 | `h30orig/prompt.txt` |
| **〔自创〕** | **本设计新增，原文无依据** | —— |

⚠️ 另有《A Complete Knowledge Base Of HUMAN 3.0》（2025-08-31）**本次未获取** ⇒ 若后续获取需复核。
🔴 **凡未标来源者视为 〔自创〕**。

---

## 0. 一页结论

### 0.1 v1 的真实缺陷（修正版）
| # | 原文 | v1 | v2 |
|---|---|---|---|
| R-1 | 四象限**各自**层级 ＋ 整体分 `Σ(层级分)/12` | **只有整体分**（算法与原文一致 ✓，但**缺象限分解** ✗）| 两者都要 ✓ |
| R-2 | 每层内 3 相位 | 无 | ✓ |
| R-3 | **Traits**（Knowledge/Experience/Skill）| 无 | ✓ |
| R-4 | **Channels + Glitches** | 无 | ✓ |
| R-5 | 输出 Metatype + Lifestyle Archetype + 核心问题 | 输出分数 + Level | ✓ |
| R-6 | 🔴 **"Never show numerical scores in output"** 〔Prompt〕| **显示分数/Level** ✗ | ✓ |
| R-7 | 假性转变 / 回退 / 跨象限解锁阻塞 | 无 | ✓ |
| R-8 | 血统 AQAL + 螺旋动力学 + 九阶段 + 心流 | 只写「Dan Koe」| ✓ |

### 0.2 ⛔ 撤回（本设计早期版本基于二手译文的错误）
| # | 早期错误说法 | 原文实际 |
|---|---|---|
| W-1 | 「原文是分子/分母结构」 | **原文无此说**；象限间机制是 Unlock/Block/Problem Chains |
| W-2 | 「原文禁止取平均」 | **错**：原文明确用 `Σ/12` |
| W-3 | 「层级判据 = 安全感来源 T/A/C」 | 原文**无 T/A/C** |
| W-4 | 「36 条确定性查表」 | 原文 Metatype 为 **AI 动态生成** |
| W-5 | 「v1 把两条正交轴压成标量」 | 过度批评；真实缺陷是**缺象限分解** |

### 0.3 🔴 U-0 定稿：**P-B′（承认这是 LLM 应用）**
评审 S-4 证明：「无 LLM 判层」与「声称忠于原文」**不能同时成立** ——
原文的层级判定本质是 **LLM 自适应追问**〔Prompt〕，去掉它就不是原框架 ✗。
⇒ **判层 + Metatype 都走 🟡 追问**（= 原文机制 ✓）；**离线/模型不可用时降级**为固定问卷 + 确定性规则（保底 ✓）。
⇒ **连带义务**：正式登记到 `decision-log.md` + 修订规划「不新增 LLM 判决点」条款（§13）。

---

## 1. 原文全貌

### 1.1 五个组成〔主文〕
Quadrants → Levels → Phases → **Traits** → **Channels**（+ Glitches）
外加：Archetypes / Metatypes、Lifestyle、False Transformation、Regression、Cross-Quadrant、Key Principles。

### 1.2 四象限（AQAL 定位）〔主文〕
| 象限 | AQAL 位置 | 定义 |
|---|---|---|
| **Mind** | Upper Left（Personal Mental）| 思想/情绪/信念/内在世界。**你如何解释世界** |
| **Body** | Upper Right（Personal Physical）| 行为与外表。**世界如何解释你** |
| **Spirit** | Lower Left（Collective Mental）| 与环境/社区/文化/家庭/朋友的关系。**如何获得意义与联结** |
| **Vocation** | Lower Right（Collective Physical）| 与系统/结构/机构（教育/职业/经济）的关系。**如何融入并贡献社会** |

> "Adapted from **Ken Wilber's AQAL model**" 〔主文〕

### 1.3 三层级（**每象限内**各有 3 个）〔主文〕
| 层 | 定义 |
|---|---|
| **1.0 Conformist** | 认同既有权威与传统；非黑即白；"只有一种正确方式"；童年塑造；外部认同；**像 NPC** |
| **2.0 Individualist** | 拒绝从众、追求自己目标；**渴求地位与被认为有价值**；相信自己的方式才正确；**主角** |
| **3.0 Synthesist** | 整合多视角；在悖论中识别真相；**创造新游戏**；**策略性选择何时显得狭隘**；**程序员** |

**两条关键原则**〔主文〕：
- **"You do not leave any given level — you transcend and include it."**
- **"Lower or higher levels are not 'bad' or 'good'."**

### 1.4 三相位（**每层内**各有 3 个，垂直发展）〔主文〕
| 相位 | 定义 |
|---|---|
| **x.1 Dissonance** | 已"尝够"当前阶段；厌倦现状但不知下一种生活是什么；**从此相位可进入 Channel** |
| **x.2 Uncertainty** | 迈出不确定的一步进入未知，向新知识与技能开放 |
| **x.3 Discovery** | 发现能带他进入下一层的教育/工具/资源/洞见 |

**记法**〔主文〕：`"Vocation 2.1"` = Level 2, Phase 1 ✓

**两个必须支持的机制**：
- **False Transformation**〔主文〕：**模仿**某层的样子却**没有对应 trait 发展**；可发生于"在某象限发展了却以为另一象限也进步" ✗
- **Regression**〔主文〕+〔Prompt〕：压力超容量或遇到超出当前层的问题时退回低层；**知识技能仍在但变得不可及** ✗

### 1.5 Traits（水平发展，三个）〔主文〕+〔Prompt〕
**Knowledge**（理论）/ **Experience**（实践）/ **Skill**（精通）。
> "Too much knowledge without experience creates **'fat personal trainer syndrome'**. … **Skill emerges from integrating both.**" 〔主文〕
> 双向陷阱：无技能经验就想升级 → **焦虑并失败**；完全不尝试升级 → **无聊并退回舒适** 〔主文〕

### 1.6 Channels + Glitches〔主文〕+〔Prompt〕
- **Channel**：Dissonance 相位可激活；强迫性学习/建造、**时间扭曲**、强迫性记录、无法停止谈论、身体兴奋感；**持续 1 周~数年**；L3 更长更频繁 〔Prompt〕
- **Glitches**（5 类）：Psychedelics / PEDs / Financial Pressure / Extreme Life Changes / **AI（唯一跨全部象限的 Meta-Glitch）**〔主文〕
- 风险分级〔Prompt〕：`L1 = Death Sentence`／`L2 = High Risk/Reward`／`L2.5+ = Calculated Risk`

### 1.7 整体分算法〔主文〕+〔Prompt〕
```
每个 Level 1 位置 = 1 分 ／ Level 2 = 2 分 ／ Level 3 = 3 分
总分 ÷ 12 = 整体发展分
```

### 1.8 Archetype 词表〔Prompt〕（主文仅有少量例子）
| 象限 | L1 | L2 | L3 |
|---|---|---|---|
| Mind | NPC, Sleeper, Programmed, Repeater, Echo, Follower | Player, Questioner, Skeptic, Contrarian, Analyst, Philosopher | Creator, Synthesizer, Architect, Systems Thinker, Meta-Mind |
| Body | Couch Potato, Skinny-Fat, Mall Walker, Diet Hopper, Inactive | Gym Bro, Cardio Bunny, Biohacker, Athlete, Fitness Influencer | Integrated Mover, Physical Artist, Body Master, Longevity Optimizer |
| Spirit | True Believer, Fundamentalist, Tribalist, Blind Faith, Follower | Spiritual Shopper, Nihilist, Hedonist, Militant Atheist, Seeker | Modern Mystic, Bridge Builder, Sacred Secular, Integral, Wise |
| Vocation | Clock Puncher, Wage Slave, Dreamer, Complainer, Cog | Hustler, Entrepreneur, Freelancer, Ladder Climber, Grinder | Mission-Driven, System Builder, Value Creator, Game Designer |

### 1.9 Lifestyle（三层 + 6 类）**〔Prompt〕**（⚠️ **主文无此内容** —— 评审 S-2）
| Lifestyle 层 | 定义〔Prompt〕|
|---|---|
| **1.0 Accidental** | 一个象限主导并抽干其它；无意识设计；**生活发生在你身上** |
| **2.0 Designed** | 靠刚性排程**强行平衡**；象限互相争夺；**生活由你发生** |
| **3.0 Integrated** | 象限自然互相支撑；**生活通过你发生** |

**6 类**〔Prompt〕：Workaholic / Seeker / Optimizer / Drifter / Specialist / Integrated（各含 Problem + Solution Path）

### 1.10 False Transformation 指标（4 象限 × 4 条）〔Prompt〕
Mind：用复杂术语不懂语境／自称开放却拒绝异见／引用领袖但无法实践／"开悟"却总被触发
Body：健身自拍但功能差／补剂替代基础习惯／极端方案只撑数周／有知识无实施
Spirit：灵性绕过真实情绪／强制正向／模仿上师无体现／遇挑战就换社群
Vocation：不存在的公司的"CEO"／工具课程上瘾无执行／教人无实战／收入套路非价值创造

### 1.11 Cross-Quadrant〔Prompt〕
**6 解锁**：Body→Spirit／Mind→Vocation／Vocation→Body／Spirit→Mind／Body→Mind／Mind→Spirit
**4 阻塞**：低 Body 阻 Spirit／低 Mind 阻 Vocation／低 Spirit 阻 Mind／低 Vocation 阻 Body
**问题链**：Vocation 解决→暴露 Spirit 空虚；Body 解决→暴露 Mind 局限；等

### 1.12 Key Principles（5 条）〔Prompt〕（主文有部分）
Transcend and Include ／ **Pre-Trans Fallacy** ／ Development Is Non-Linear ／ Life Is Problem-Solving ／
**Multi-Level Straddling**（"Knowledge can be Level 3 while experience remains Level 1"）🔴 **§5.3 必须支持**

---

## 2. 判定机制（**P-B′ 定稿**）

| 环节 | 主路径 | 降级路径（离线/模型不可用）|
|---|---|---|
| **层级判定** | 🟡 **LLM 自适应追问**〔Prompt〕：每象限 3~8 题、一次一问、**追问到确信** | 〔自创〕固定问卷 + 确定性规则（§5.3）|
| **相位** | 🟡 追问中判定〔Prompt〕 | 〔自创〕固定 1 题三选一 |
| **Traits** | 🟡 追问中判定〔Prompt〕 | 〔自创〕固定 3 题 + 三档计分 |
| **Metatype** | 🟡 **AI 动态生成**〔主文〕（原文明确拒绝静态测试）| 查 Archetype 词表 + 整体档位 |
| **整体分 `Σ/12`** | 确定性 ✓〔主文〕 | 同 |

### 2.1 🔴 追问是**必需**的（评审 S-4）
原文的追问是**防自欺的核心机制**〔Prompt〕：
> "你说你懂 X——那每天怎么用？"／"听起来很理想——做不到时怎么办？"／"Continue probing until confident"

⇒ **降级路径（固定三选一）本质上会丢失这一机制** ⇒ 降级时必须**明示"这是自评映射，非原框架判定"** ✗（§8.3）。

---

## 3. 架构
```
fg_system/human30/
├── __init__.py       # 对外 API（兼容 v1 全部函数）
├── model.py          # 常量：象限/层级/相位/Traits/Archetype 词表/Lifestyle/指标表
├── store.py          # 读写 + 原子写 + 损坏抛错 + 懒迁移
├── assess.py         # 判层 + 相位 + Traits + 假性转变/回退 + 跨象限（含 🟡 与降级双路）
└── metatype.py       # 整体分 + Lifestyle + Metatype（🟡）
fg_system/human30.py  # 薄兼容层：re-export（旧调用点不改）
```
**约束**：v1 既有对外函数签名与返回结构**不得破坏** ⇒ `scripts/invest_research.py:650`、
`fg_system/dashboard/report.py:711`、`fg_system/dashboard/server.py:195/154` **无需同时修改** ✓

### 3.1 🔴 兼容策略：**新增，不复用**（评审 C-1）
v1 `aggregate()["level"]` 的语义是「**整体均分档**」（`avg<40→1`）。
**若把它改成"最弱象限的层"，签名不变但值变了** ⇒ 看板主卡会从「L2 综合者」**静默变成**
「L1 从众者」（某象限 <40 时），而调用点**一个字不改** ✗ —— 这是不可接受的静默行为变更 ✗。

⇒ **定死**：
- `aggregate()["level"]` **保留旧语义**（整体均分档）**不变** ✓
- v2 的象限分解**另开字段/函数**：`aggregate()["quadrant_levels"]`、`["weakest_level"]` ✓
  （**只增 key，不改旧 key 的值** ✓）
- **禁止**把 v2 语义塞进旧 key ✗

> 被消费的旧 key（`report.py:721-727` 用 `avg`/`level`/`level_name`；`invest_research.py:650-678`
> 经 `brief_line()` 用 `level_name`；`human30_review.py:46,96-104` 用 `level_name`；
> `human30_cli.py:50` 用 `level_name`）**全部保持原义** ✓

---

## 4. 数据模型与迁移

### 4.1 记录结构
```jsonc
// v1 旧记录（原样保留，读取时映射）
{"date":"2026-10-01","mind":65,"body":55,"spirit":60,"vocation":50,"note":"...","market":{...}}

// v2 新记录
{"date":"2026-10-14","schema":2,
 "mind":65,"body":55,"spirit":60,"vocation":50,
 "levels":{"mind":2,"body":2,"spirit":1,"vocation":2},
 "level_detail":{"mind":{"answers":[2,2,3],"straddling":true,"confidence":"medium","source":"llm|fallback"}},
 "phases":{"mind":"dissonance",...},
 "traits":{"mind":{"knowledge":3,"experience":2,"skill":2}},
 "flags":{"mind":{"false_transformation":false},"body":{"regression":true}},
 "assessment":{"mind":{"q":[{"q":"...","a":"...","probe":"..."}]}},   // 追问原文（可审计）
 "note":"...","market":{...}}
```

### 4.2 迁移规则（**懒迁移**）
- 旧记录 `levels[q]` = 分档映射（`>70→3`／`40..70→2`／`<40→1`）**〔自创〕**
- 旧记录 `phases[q]` = **一律 `"unknown"`**（不猜测）
- **只在读取时进行** ⇒ 不重写文件、不丢原始字段、可逆 ✓

### 4.2.1 🔴 必须重写 `record()` 的落盘逻辑（评审 C-3）
v1 现状（`human30.py:133-138`）：
```python
data = _load()
data["records"] = [r for r in data["records"] if r.get("date") != rec["date"]]  # 删同日旧记录
data["records"].append(rec)                                                     # 追加新记录
data["records"].sort(key=lambda r: r["date"])                                   # 全量重排
_save(data)                                                                     # 整文件重写
```
⇒ **三个真实缺陷** ✗：
1. **新增一条记录会重写并重排全部历史** ✗ ⇒ 与"懒迁移不重写文件"矛盾 ✗
2. `sort(key=lambda r: r["date"])` 用 `r["date"]` 而非 `r.get` ⇒ 畸形记录 **KeyError** ✗
3. **同日二次打卡会丢字段** ✗ —— 行 135 按 date 删旧、行 136 只 append 新 `rec`，
   而 `rec` 只含 `date/mind/body/spirit/vocation/note/market` ⇒ **v2 新字段（`levels`/`phases`/`traits`/`flags`/`assessment`/`schema`）会被抹掉** ✗

⇒ **定死**：
- `store.append()` 必须做「**同日合并**」（读到同日旧记录 → **深合并** v2 字段）**而非"删旧+append"** ✗
- 序列化时**保留所有未知字段**（不得因白名单丢字段）✓
- 排序用 `r.get("date")`，畸形记录**不崩**（跳过或置后）✓
- **只在确实有变更时才 `_save`** ✓

### 4.3 数据安全（继承 v1 的 S-2 修复，**不得回退**）
`_save()` = tmp + fsync + os.replace；`_load()` 遇损坏**抛 RuntimeError**（不得静默空历史）；
`tests/test_human30_robustness.py` 必须保留并通过 ✓

---

## 5. 判定（双路：🟡 主路径 + 确定性降级）

### 5.1 🔴 主路径：🟡 LLM 自适应追问〔Prompt〕
- 每象限 **3~8 题**、**一次一问**、追问到确信〔Prompt〕
- 层级分支：检测到 L1 → 问信念来源/模糊容忍/对批评的反应；L2 → 问盲点/对立观点整合/元认知；L3 → 问有意限制策略/建构意识/教学创造〔Prompt〕
- 假性转变探测：5 条追问〔Prompt〕
- 特殊情形：Active Channel / Regression / Glitch 使用者探测〔Prompt〕
- **输出**：`levels` + `level_detail`（含追问原文）+ `phases` + `traits` + `flags`

### 5.2 降级路径：固定问卷（**〔自创〕**）
⚠️ 以下**全部为〔自创〕**：题干是官方问题的**中译**〔Prompt〕，**选项文本原文没有**。

**层级问卷（4 象限 × 3 题，每题三选一 → 1/2/3）**
| 象限 | 题 1（官方中译）| 题 2 | 题 3 |
|---|---|---|---|
| Mind | 遇到与你世界观矛盾的观念，第一反应？ | 你如何判断信息真伪/价值？ | 上次重大信念改变由什么触发？ |
| Body | 你和身体的关系是盟友/敌人/工具？ | 健康决策由什么驱动？ | 生活混乱时身体实践还保持吗？ |
| Spirit | 一切无意义时你如何获得意义？ | 社群对你：必需/可选/内在？ | 绝对真理 vs 相对视角？ |
| Vocation | 工作是"你做的/你有的/你就是"？ | 如何衡量职业成功？ | 若钱与地位无关你会做什么？ |

### 5.3 降级判层规则（**〔自创〕**，已按评审 M-4/M-5 修正）
```
三题得分 [a,b,c]
- 若三题一致            → level = 该值, confidence = "high"
- 若两同一异            → level = 多数值, confidence = "medium", straddling = true
- 🔴 若三题互不相同      → level = null, confidence = "low", straddling = true
                            （**禁止静默取中位数** —— 评审 M-4：那会系统性归到 L2）
```
🔴 **必须保留三题分布**（`level_detail.answers`）以支持 **Multi-Level Straddling**〔Prompt〕
（"知识可 L3 而经验仍 L1"）—— 不得只输出单一层级 ✗

🔴 **假性转变交叉校验**（评审 M-4）：若自评为 L3 却命中该象限 §1.10 指标 ≥1 条
⇒ 降 `confidence` + 打 `false_transformation` 标 ✓

### 5.4 相位 / Traits / Channel / Glitch（降级路径）
| 项 | 做法 | 来源 |
|---|---|---|
| 相位 | 1 题三选一（厌倦停滞／摸索中／已找到方法）| 选项〔自创〕，概念〔Prompt〕|
| Traits | 3 题（能解释不能实践／做过没想透／曾费力如今自然）| 题干〔Prompt〕，三档计分〔自创〕|
| Channel | 日频 1 题「最近是否处于停不下来的专注期？」| 〔自创〕|
| Glitch | 按整体分给提示：`<2.0` 建议自然发展／`2.0~2.5` 谨慎／`≥2.5` 可考虑 | 分级概念〔Prompt〕，阈值映射〔自创〕|

### 5.5 评估节奏（双层）
| 层 | 频率 | 内容 | 忠实度 |
|---|---|---|---|
| **日频** | 每天（允许断档）| 状态分 + 相位题 + Channel 题 | ⚠️ **〔自创〕**，原文无"每日打卡"，须明标 |
| **周期性** | 30 天（原文有 30/90/180 节奏〔Prompt〕）| 🟡 完整追问（或降级为完整问卷）| ✓ 忠实 |

---

## 6. 确定性可做部分
| 能力 | 来源 | 需 LLM |
|---|---|---|
| 整体分 `Σ/12` | 〔主文〕| ❌ |
| Archetype 名称 | 〔Prompt〕词表 | ❌ |
| Lifestyle Archetype | 〔Prompt〕6 类 + 象限分布 | ⚠️ 阈值〔自创〕|
| Unlock/Block 提示 | 〔Prompt〕6+4 条 | ❌ |
| False Transformation 清单 | 〔Prompt〕16 条 | ❌ |
| Glitch 风险分级 | 〔Prompt〕三级 | ❌ |
| 跨象限问题链 | 〔Prompt〕| ❌ |
| 四象限层级 / 相位 / Traits | 主路径 🟡；降级确定性 | 主路径 ✅ |
| Metatype 命名 + 叙述 | 〔主文〕= AI 生成 | ✅ |

---

## 7. 输出格式〔Prompt〕（照搬官方）
```
HUMAN 3.0 DEVELOPMENT ASSESSMENT RESULTS
YOUR METATYPE: [Dynamic Name] + 2-3 句                        ← 🟡 必须 LLM
YOUR LIFESTYLE ARCHETYPE: [Name] + 描述                       ← 确定性可算
QUADRANT BREAKDOWN: 📊 Mind/Body/Spirit/Vocation              ← 确定性可算
  Archetype / Current Phase / Consciousness Level / Strengths / Gaps /
  Lifestyle Impact / False Transformation Alert
CROSS-QUADRANT DYNAMICS: Primary Block / Unlock / Hidden Pattern / Cascade  ← 确定性可算
YOUR CORE PROBLEM TO SOLVE: [那一个能引发最大正向级联的问题]    ← 🟡 建议 LLM
LIFESTYLE TRANSFORMATION STRATEGY: 30 天 / 90 天 / 6-12 个月   ← 🟡 部分需 LLM
GLITCH ASSESSMENT: 按整体分三级                                ← 确定性可算
⚠️ CRITICAL WARNINGS: Regression / False Transformation / Cascade / Lifestyle / Glitch
COMPARABLE METATYPES: Similar to / Overlaps with / Could evolve toward  ← 🟡
YOUR IMMEDIATE NEXT ACTION: 24 小时内可完成的动作                ← 🟡
THE TRUTH ABOUT YOUR SITUATION: 1-2 段直白反馈                  ← 🟡
```
### 7.1 🔴 硬约束（评审 M-3/M-6/M-7/M-9）
1. **"Never show numerical scores in output"**〔Prompt〕⇒ 输出**不得出现 0-100 分与 Level 数字** ✓
   - ⚠️ 说明（评审 M-7）：**内部**仍用数字（`Σ/12`、分档）✓，但**对外表述**一律转成 Archetype 名/档位词 ✓
     —— 理由是原文的**用户界面**不用数字，而非"不计算数字" ✓
2. **§7 输出字段禁止出现交易动词**（减仓/加仓/买入/卖出/仓位/止损…）✓
3. **🟡 字段必须标注**（前缀 `AI 复盘（🟡 研究参考，非系统信号）`）且**不入任何下游** ✓
4. **偏离标注**（评审 M-9）：原文在 L2.5+ 会给出 "Most aligned with your development: [Specific Glitch type]"
   ⇒ **本设计主动删除具体 Glitch 推荐，只做风险提示** ✗（安全考虑，明示偏离）✓

---

## 8. 看板与简报
| 项 | v1 | v2 |
|---|---|---|
| 主卡 | 全局 Level + 均分（**显示数字** ✗）| 四象限 Archetype 名 + `Vocation 2.1`（**不显示分数** ✓）|
| 雷达图 | 四象限分数 | **层级位置图**（4 轴 × 3 档）✓ |
| Lifestyle | 无 | Lifestyle Archetype + 主 Problem ✓ |
| Metatype 卡 | 无 | 🟡 生成（默认 Archetype + 整体档位）✓ |
| 简报 | 「🌱 Human 3.0 状态」 | 象限 Archetype/相位 + 核心问题一行（🟡 明标）✓ |

### 8.1 🔴 跨机问题（评审 M-8）
`Data/human30.json` 在 **Mac 本地**、不入库 ⇒ **Windows 侧读不到** ✗
⇒ **本模块的看板/简报定位为「Mac 侧功能」** ✓；Windows 侧必须显示
「本机无 Human 3.0 数据（数据在 Mac 本地）」**而非空白/空壳** ✓
⇒ 跨机同步**不在本设计范围**（如需，另立提案）✓

### 8.2 看板不得崩（`b22edc4` 前车之鉴）
`human30_json` 注入 + `default('null')` 兜底**必须保留** ✓

### 8.3 降级路径必须明示（评审 S-4）
走降级（固定问卷）时，输出**必须**带一行：
> 「本结果由固定问卷的确定性映射得出，**非原框架的追问判定**；可信度低于 🟡 版」

---

## 9. 测试策略
### 9.1 单元测试
| 单元 | 必测 |
|---|---|
| `store` | 旧记录读取/映射；往返一致；损坏抛错；原子写（**继承 S-2 守卫**）|
| `assess` | 🟡/降级双路；判层规则边界（含**互异不得静默取中位数**）；straddling 保留；假性转变交叉校验 |
| `metatype` | `Σ/12` 边界（1.0/3.0）；Lifestyle 判定；Archetype 词表无缺；🟡 降级 |
| 兼容层 | v1 全部公开函数签名与返回结构不破 |

### 9.2 🔴 守卫测试（采纳评审角色 B 的 14 条）
```
# 红线② LLM 不裁决 / 不进判决链
1  test_human30_not_imported_by_decision.py      # pipeline/signal/backtest/risk 不得 import human30
2  test_metatype_never_reaches_position.py       # 产物不得出现在 target_position/ZONE_EDGES/CORE_CAP
3  test_metatype_requires_registered_exception.py# ⚠️ 见 §9.3 修正：只对 🟡 判层入口检查，**不得**放在 import 路径上
4  test_metatype_failure_degrades_deterministically.py
# 输出约束
5  test_no_numeric_score_in_rendered_output.py   # 禁 "xx/100"、禁 "Level 1/2/3"
6  test_output_no_trade_verbs.py                 # NEXT ACTION 等字段禁交易动词
# 红线③ Data 不入库 / 不外发
7  test_human30_data_is_gitignored.py
8  test_human30_data_not_in_feishu_bundle.py
# 数据安全（继承 S-2，不可回退）
9  tests/test_human30_robustness.py 全保留
10 test_lazy_migration_is_lossless.py            # 旧字段一个不丢、写回不重排
# §15 隔离
11 test_L1_L2_L3_output_is_text_only.py
12 test_human30_never_invokes_decision_chain.py
# 判层规则
13 test_level_rule_all_distinct_is_not_silent_median.py
14 test_false_transformation_crosscheck.py
```

### 9.3 🔴 守卫 3 的放置位置（评审 C-2）
⚠️ **若把"必须已登记"硬绑在 `import human30` 上，今天仓库会全线崩** ✗ ——
`test_human30.py` / `test_human30_robustness.py` / `test_human30_review.py` /
`human30_cli.py:24` / `report.py:717,739` / `invest_research.py:654`
**全部**会 raise（当前 `decision-log.md` 无 H-REV-001 登记）✗。

⇒ **定死**：
- 守卫 3 **只对 🟡 判层入口**检查（`assess.judge_via_llm()` / `metatype.generate()`）✓
- **不得**放在包 `__init__` / `store` / `assess` 的 **import 路径**上 ✗
- **登记（H-REV-001）必须先于该守卫落地** ✓
- 守卫 3 归入 **P4**（🟡 主路径上线时）✓

---

## 10. 边界与纪律
1. **不进交易判决链**：不参与 `pipeline`/`signal`/`target_position`/仓位 ✓（§9.2-1/2/12 守卫）
2. **LLM 使用已登记**：🟡 追问 + Metatype ⇒ **必须在 `decision-log.md` 登记 + 修订规划条款**（§13）✓
3. **数据只读 + 不入库**：`.gitignore:116` 已忽略 `Data/human30.json` ✓（**主线**；本地工作区缺 ✗）
4. **不外发**：不进任何外发包 ✓（§9.2-8 守卫）
5. **输出不显示数字分数**〔Prompt〕✓
6. **输出不含交易动词** ✓
7. **不做线性进步叙事**（"不是越高越好"〔主文〕）✓
8. **不做具体 Glitch 推荐**（主动偏离〔Prompt〕，明示 ✓）

---

## 11. 分期计划
| 期 | 内容 | 验收判据 |
|---|---|---|
| **P0** | spec + C-2 提案 + **U-0 决策 + H-REV-001 登记 + 规划条款修订** | 你批准 |
| **P1** | `model.py`（词表/指标表/6 类 Lifestyle）+ `store.py`（**含 C-3 修法：同日合并落盘**）；`aggregate()` **只增 key 不改旧值**（C-1）| 旧数据全可读；往返一致；S-2 守卫全绿；守卫 10/13 通过 |
| **P2** | `assess.py` 降级路径（固定问卷 + 确定性规则 + straddling + 交叉校验）| 规则可复算；守卫 13/14 通过 |
| **P3** | 整体分 `Σ/12` + Lifestyle + Archetype + 跨象限 + 假性转变/回退 | 与原文算法一致 |
| **P4** | `assess.py` **🟡 追问主路径** + `metatype.py`（🟡）+ 官方输出格式 | 守卫 1~6 通过；降级可用 |
| **P5** | 看板 / 简报升级（去数字、层级图、跨机提示）| 三种渲染不崩；无数字；无交易动词 |
| **P6** | 文档 / 制度收口（§13）| — |

---

## 12. 制度收口（P6）
- `docs/system-boundary.md` 新增一节：**「Human 3.0 不进判决链」**
- `docs/decision-log.md` 补记：引入依据（2026-10-10 用户拍板）+ v2 重设计依据 + **H-REV-001 正式登记**
- `docs/2026-10-11-贪恐系统发展迭代规划.md`：**修订「不新增 LLM 判决点」条款**（U-0 连带义务）
- `docs/roadmap.md` 新增条目：Human 3.0（含「数据在 Mac 本地 / 待做预登记对照」）
- `docs/human30.md` 与本文**合并为一份**（U-5）

---

## 13. 未决项
| # | 未决 | 状态 |
|---|---|---|
| U-0 | 忠于原文 ⟺ 无 LLM 判决 | ✅ 已定：**P-B′**（承认是 LLM 应用）|
| U-2 | 评估节奏 | ✅ 已定：**双层** |
| U-3 | Channels / Glitches | ✅ 已定：**都实现，只做只读提示** |
| U-4 | 问卷频率 | ⚠️ 作废（改由 §5.5 双层定义）|
| U-5 | v1/v2 文档合并 | ✅ 已定：**合并为一份** |
| **U-6** | ~~角色 D 的终极质问~~ | ✅ **已定（2026-10-14，用户）：「追问保留，值得做」** ⇒ §2.1 追问为**主路径**，降级路径**不得作为默认** ✓ |
| **U-7** | **角色 C（工程可行性）评审未返回** ⇒ 需补做 | 🔴 **待补** |
| **U-8** | **本地落后主线 321 提交** ⇒ 开发前必须先对齐 | 🔴 **待办** |

---

## 14. 与贪恐系统的联系（**已按评审 S-5 降级**）

### 14.1 原文自身的象限间机制〔Prompt〕
Unlock（6 条）／ Block（4 条）／ Problem Chains ／ **Life Is Problem-Solving**〔主文〕
（⚠️ 本设计早期版本的"分子/分母"说法**已撤回**，原文无此说）

### 14.2 三条潜在联系 —— **降级为「仅记录不分析」**
| # | 联系 | 状态 |
|---|---|---|
| L-1 | 执行偏差归因（极端档位 × 相位 → 执行偏差）| ⏸ **不实现** |
| L-2 | 断档模式（断档是否集中在回撤期）| ⏸ **不实现** |
| L-3 | 反向传染（极端档位 → 状态恶化）| ⏸ **不实现** |

**理由（评审 S-5）**：日频 1 条，「极端档位 + 失调相位」**一年可能仅个位数** ⇒ 统计功效极低 ✗
⇒ 个位数样本上做显著性检验 = **用噪声讲因果故事** ✗ ⇒ **不写进 roadmap，仅记录不分析** ✓
⇒ 待 1~2 年数据积累后再评估（另立提案）✓

### 14.3 红线
- ❌ **禁止**：用 Human 3.0 状态**改变交易判决**（"unease 高 ⇒ 降仓位"）
- ⚠️ **修正（评审 M-1）**：~~"允许提醒人（今天别动手）"~~ ⇒ **仅允许展示统计事实**
  （如"历史样本显示该相位期执行偏差更大"），**禁止祈使句形式的时点指令** ✓

### 14.4 隔离守卫
L-1/L-2/L-3 若将来实现，产物**只能是 `str` 描述性文本**，与 `pipeline`/`signal`/`target_position`
**无 import 边**（§9.2-1/2/11/12 守卫）✓

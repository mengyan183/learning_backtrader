# fg_system/human30/model.py
# -*- coding: utf-8 -*-
"""Human 3.0 常量与词表。

来源标记（见 docs/human30-v2-design.md 约定）：
  〔主文〕  = HUMAN 3.0 – A Map To Reach The Top 1%（2025-08-26）
  〔Prompt〕= Prompt: HUMAN 3.0 Self-Discovery & Metatype Test（2025-08-27）
  〔自创〕  = 本设计新增，原文无依据
"""
QUADRANTS = ["mind", "body", "spirit", "vocation"]          # 〔主文〕
LABELS = {"mind": "心/认知", "body": "体/行动",
          "spirit": "精神/意义", "vocation": "职/事业"}      # 〔自创〕中文标签

# AQAL 位置〔主文〕
AQAL_POSITIONS = {
    "mind": "Upper Left (Personal Mental)",
    "body": "Upper Right (Personal Physical)",
    "spirit": "Lower Left (Collective Mental)",
    "vocation": "Lower Right (Collective Physical)",
}

LEVELS = {                                                  # 〔主文〕
    1: ("1.0 顺从者 Conformist", "安全感来自传统·外部权威·非黑即白·像 NPC"),
    2: ("2.0 个体主义者 Individualist", "安全感来自成就·内在权威·渴求地位·主角"),
    3: ("3.0 综合者 Synthesist", "安全感来自接纳·多视角整合·创造新游戏·程序员"),
}

PHASES = ["dissonance", "uncertainty", "discovery"]          # 〔主文〕
PHASE_LABELS = {"dissonance": "失调", "uncertainty": "不确定",
                "discovery": "发现", "unknown": "未知"}

TRAITS = ["knowledge", "experience", "skill"]                # 〔主文〕+〔Prompt〕

# Archetype 词表〔Prompt〕
ARCHETYPES = {
    "mind": {
        1: ["NPC", "Sleeper", "Programmed", "Repeater", "Echo", "Follower"],
        2: ["Player", "Questioner", "Skeptic", "Contrarian", "Analyst", "Philosopher"],
        3: ["Creator", "Synthesizer", "Architect", "Systems Thinker", "Meta-Mind"],
    },
    "body": {
        1: ["Couch Potato", "Skinny-Fat", "Mall Walker", "Diet Hopper", "Inactive"],
        2: ["Gym Bro", "Cardio Bunny", "Biohacker", "Athlete", "Fitness Influencer"],
        3: ["Integrated Mover", "Physical Artist", "Body Master", "Longevity Optimizer"],
    },
    "spirit": {
        1: ["True Believer", "Fundamentalist", "Tribalist", "Blind Faith", "Follower"],
        2: ["Spiritual Shopper", "Nihilist", "Hedonist", "Militant Atheist", "Seeker"],
        3: ["Modern Mystic", "Bridge Builder", "Sacred Secular", "Integral", "Wise"],
    },
    "vocation": {
        1: ["Clock Puncher", "Wage Slave", "Dreamer", "Complainer", "Cog"],
        2: ["Hustler", "Entrepreneur", "Freelancer", "Ladder Climber", "Grinder"],
        3: ["Mission-Driven", "System Builder", "Value Creator", "Game Designer"],
    },
}

# Lifestyle 6 类〔Prompt〕（主文无此内容）
LIFESTYLE_ARCHETYPES = [
    {"name": "The Workaholic", "trait": "Vocation 占 80%+ 能量",
     "problem": "事业成功以其他一切为代价",
     "solution": "自动化/委派以腾出时间，再重建其他象限"},
    {"name": "The Seeker", "trait": "Spirit/Mind 重，Body/Vocation 弱",
     "problem": "用灵性绕过物质现实",
     "solution": "用身体实践与价值创造把洞见落地"},
    {"name": "The Optimizer", "trait": "Body/Mind 专注，Spirit/Vocation 浅",
     "problem": "孤立地打磨自己",
     "solution": "把优化应用到关系与有意义的工作"},
    {"name": "The Drifter", "trait": "无象限深度发展",
     "problem": "缺乏焦点，无法真正推进",
     "solution": "选一个象限作为发展锚点"},
    {"name": "The Specialist", "trait": "一个象限 L3，其余 L1",
     "problem": "失衡限制了专长的影响力",
     "solution": "在弱项做最小可行发展"},
    {"name": "The Integrated", "trait": "全象限 L2+，互相支撑",
     "problem": "在成长期维持整合",
     "solution": "有意识地演化并教别人"},
]

# 假性转变指标〔Prompt〕（4 象限 × 4 条）
FALSE_TRANSFORMATION = {
    "mind": ["用复杂术语但不懂语境", "自称开放却拒绝异见",
             "引用思想领袖但无法实践", "「开悟」了却总被触发"],
    "body": ["健身自拍但功能动作差", "补剂堆栈替代基础习惯",
             "极端方案只坚持数周", "有知识无实施"],
    "spirit": ["用灵性绕过真实情绪", "「爱与光」式强制正向",
               "模仿上师而无体现", "遇挑战就换社群"],
    "vocation": ["不存在的公司的「CEO」", "沉迷工具/课程而无执行",
                 "教别人却无实战结果", "收入套路而非价值创造"],
}

# 跨象限〔Prompt〕
UNLOCK_SEQUENCES = [
    ("body", "spirit"), ("mind", "vocation"), ("vocation", "body"),
    ("spirit", "mind"), ("body", "mind"), ("mind", "spirit"),
]
BLOCK_PATTERNS = [
    ("body", "spirit"), ("mind", "vocation"),
    ("spirit", "mind"), ("vocation", "body"),
]

KEY_PRINCIPLES = [                                          # 〔Prompt〕
    "Transcend and Include",
    "Pre-Trans Fallacy",
    "Development Is Non-Linear",
    "Life Is Problem-Solving",
    "Multi-Level Straddling",
]

# 整体分算法：Σ(层级分)/12〔主文〕+〔Prompt〕
TOTAL_SLICES = 12

# 引导式问答打卡（v1 原有，〔自创〕；5 级 Likert → 20/40/60/80/100）
QUESTIONS = {
    "mind": "今天我能清晰思考，不被情绪带着走",
    "body": "今天我的精力足以执行计划",
    "spirit": "今天做的事让我觉得有意义",
    "vocation": "今天我在事业/职业上推进了重要事项",
}
LIKERT_SCORES = {1: 20, 2: 40, 3: 60, 4: 80, 5: 100}

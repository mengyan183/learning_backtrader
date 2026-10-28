#!/usr/bin/env bash
# 提交前**纪律门禁**（§8 文档先行）：改了「规则代码」却没同步改 docs/ ⇒ 拒绝提交。
#
# 【为什么需要】
# docs/trading-discipline.md 第 8 条：文档 → 代码 → 回测 → 验证，顺序不可颠倒。
# 2026-10-27 决定给 Mac 侧引入 AI agent 后，agent 能直接改规则代码并 commit；
# 而 Mac 是**唯一能 push 的端**（Windows 被公司策略禁止 push）⇒ 坏改动会直通
# gitee 再回流到 Windows ✗。记录教训不够，必须有机制拦住它 —— 同 §12.27-⑩ 的思路。
#
# 【检查什么】
# 暂存区里出现「规则代码」⇒ 必须同时有 docs/ 下的变更 ✓（§8.3：参数改动与
# 规则改动同等对待，所以 config.py 的阈值/权重也算规则改动）。
#
# 【规则代码范围】见 RULE_PATHS —— 改动会直接影响信号与仓位：
#   fg_system/signal/     信号与仓位（core_position / market_core / batches_for）
#   fg_system/models/     指数模型（hmm / markov / bayes / evt）
#   fg_system/config.py   阈值、权重、窗口、映射表
#
# 用法：
#   bash scripts/pre-commit-discipline.sh              # 检查 git 暂存的文件（hook 用）
#   bash scripts/pre-commit-discipline.sh a.py b.md    # 检查指定文件（便于测试）
#
# 安装（🔴 两端不同 —— `pre-commit-syntax.sh` 在 .gitignore 的「本机专用」清单里，
# 不会随仓库同步 ✗；本脚本是**跟踪**的 ✓，会随同步到达 Mac）：
#   Windows：已由 pre-commit-syntax.sh 末尾调用 ✓
#            cp scripts/pre-commit-syntax.sh .git/hooks/pre-commit
#   Mac：在 .git/hooks/pre-commit 末尾自己加一行：
#            bash scripts/pre-commit-discipline.sh || exit 1
#        （Mac 是**唯一能 push 的端** ⇒ 这道门在 Mac 上比在 Windows 上更重要 ✗）
set -u

RULE_PATHS="fg_system/signal/ fg_system/models/ fg_system/config.py"

if [ "$#" -gt 0 ]; then
    targets="$*"
else
    targets=$(git diff --cached --name-only --diff-filter=ACM || true)
fi

rule_files=""
doc_files=""
for f in $targets; do
    case "$f" in
        docs/*) doc_files="$doc_files $f" ;;
    esac
    for p in $RULE_PATHS; do
        case "$f" in
            "$p"*) rule_files="$rule_files $f" ;;
        esac
    done
done

[ -z "$rule_files" ] && exit 0

if [ -n "$doc_files" ]; then
    echo "✓ 纪律门禁：规则代码变更已附带文档变更"
    exit 0
fi

echo "❌ 纪律门禁：改了规则代码，但 docs/ 下没有任何变更。"
echo "   规则代码：$rule_files"
echo ""
echo "   docs/trading-discipline.md 第 8 条：顺序不可颠倒"
echo "     1. 先改文档（本规范 + 技术设计文档）"
echo "     2. 再改代码"
echo "     3. 再回测验证（必须包含样本外区间）"
echo "     4. 验证通过后才生效"
echo ""
echo "   ⇒ 先补 docs/ 下的变更（哪怕只记录「为什么改」），再一起提交。"
echo "   ⇒ 若本次只是重构/改注释、不影响规则语义，把它移出暂存区，或拆成两次提交。"
exit 1

#!/bin/bash
# ==========================================================================
# Mac 端首次引导还原 —— 把飞书聊天记录 / 云文档导出的分片还原成仓库。
#
# 为什么需要（2026-09-28 实测踩到的鸡生蛋）：
#   keep / minimal / tests 三个包里**没有解包工具**，而解包工具本身就在包里
#   ⇒ 首次引导必须靠一段**不依赖仓库任何文件**的脚本 —— 就是本文件。
#   make_feishu_bundle.py 把它 base64 后以 bootstrap-t* 分片发出，
#   排序保证它排在所有包之前，feishu_send.py 正好先发这几条。
#
# 用法（Mac 上）：
#   1. 把飞书聊天记录全选复制 / 云文档「下载为 Markdown」导出，
#      粘进一个目录（默认 ~/Downloads/fg），文件可以是 .txt 或 .md
#   2. bash mac_bootstrap.sh
#
# 它做五件事：还原飞书转义 -> 提取分片 -> 报告缺片/混包/非 xz -> 解压 -> 打印后续步骤
#
# ⚠️ 约定：`python3 - <<'PY'` 这一行是 make_feishu_bundle 测试提取主体的锚点，
#    不要改成带参数/前缀变量的写法（会断掉"拼回逐字节一致"的验收）。
# ==========================================================================
set -uo pipefail

SRC="$HOME/Downloads/fg"
DEST="$HOME/learning_backtrader"

if [ ! -d "$SRC" ]; then
    echo "❌ 目录不存在：$SRC"
    echo "   请先把飞书聊天记录粘成一个 .txt/.md 放进这个目录"
    exit 1
fi
SRC="$(cd "$SRC" && pwd)"

echo "分片目录：$SRC"
echo "还原到：  $DEST"
echo

mkdir -p "$DEST"
cd "$DEST" || exit 1

python3 - <<'PY'
import base64, glob, io, os, re, sys, tarfile

# 这两个字面量是 make_feishu_bundle 测试替换的锚点，别改成 argv 取值
src = os.path.expanduser("~/Downloads/fg")
dest = os.path.expanduser("~/learning_backtrader")

files = sorted(glob.glob(os.path.join(src, "*.txt")) +
               glob.glob(os.path.join(src, "*.md")))
if not files:
    sys.exit("❌ %s 下没有 .txt / .md 分片文件" % src)

text = "".join(open(p, encoding="utf-8", errors="ignore").read() for p in files)

# ⚠️ 飞书「下载为 Markdown」会把 `#` 转义成 `\#`、把 `+` 转义成 `\+`
#    （2026-09-28/29 实测）。不还原则一个标记都匹配不到 / base64 解码报错。
#    base64 正文不含 `#`/`\` ⇒ 替换不会伤到数据。
text = text.replace("\\#", "#").replace("\\+", "+")

pat = re.compile(r"###FG:([A-Za-z0-9_]+):(\d+)/(\d+)###(.*?)###FG:end###")
parts, totals_seen = {}, {}
for name, i, total, body in pat.findall(text):
    parts.setdefault(name, {})[int(i)] = "".join(body.split())
    totals_seen.setdefault(name, set()).add(int(total))

if not parts:
    sys.exit("❌ 没找到 ###FG: 标记 —— 聊天记录要**全部**复制（往上滚到顶）")

bad = False
for name in sorted(parts):
    totals = sorted(totals_seen[name])
    # 同一个包出现多个不同总数 ⇒ 目录里混了旧一次导出，必须点名警告
    #（实测踩到：新旧混拼会让"缺片"判断全错）。
    if len(totals) > 1:
        print("⚠️ 包 %-8s 混了旧导出（同时见到 %d 个不同总数：%s）—— "
              "建议清空目录只留最新一次导出" % (name, len(totals), totals))
        continue
    want = totals[0]
    got = len(parts[name])
    missing = [i for i in range(1, want + 1) if i not in parts[name]]
    if missing:
        print("❌ %-8s 只有 %d/%d 片，缺第 %s 片"
              % (name, got, want, missing[:12]))
        bad = True
        continue
    blob = base64.b64decode("".join(parts[name][i] for i in range(1, want + 1)))
    if blob[:6] != b"\xfd7zXZ\x00":
        # 非 xz 数据（如引导脚本自身的 base64、老导出残留）只能警告，
        # 不能把整体判成「传输缺片」——那是把用户引向错误方向（实测踩到）。
        print("⚠️ %-8s 不是 xz 包（%d 字节）—— 跳过，不视为失败"
              % (name, len(blob)))
        continue
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:xz") as tf:
        tf.extractall(dest)
    print("✅ %-8s %d/%d 片 -> 已解压" % (name, got, want))

if bad:
    sys.exit("\n⚠️ 有缺片。回到公司电脑补发，例如：\n"
             "   python scripts/feishu_send.py --start <缺的那片序号>")
PY

rc=$?
echo
if [ $rc -ne 0 ]; then
    echo "❌ 还原未完成（见上面的提示）"
    exit $rc
fi

echo "✅ 还原完成。接着建环境并自检："
echo
echo "   cd $DEST"
echo "   export FG_PROXY=\"\"        # ⚠️ 公司代理在 Mac 上不通，必须置空"
echo "   python3.10 -m venv .venv"
echo "   .venv/bin/pip install -r requirements.txt"
echo "   .venv/bin/python scripts/bootstrap_data.py    # 抓行情数据（2~5 分钟）"
echo "   .venv/bin/python -m pytest -q                 # 自检"

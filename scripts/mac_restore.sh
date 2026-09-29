#!/bin/bash
# ==========================================================================
# Mac 端一键还原 —— 把飞书聊天记录里的 58 条消息还原成可运行的仓库
#
# 用法（Mac 上）：
#   1. 把飞书聊天记录全选复制，粘进一个文件，例如 ~/Downloads/fg/note.txt
#   2. bash mac_restore.sh [聊天记录所在目录]     # 默认 ~/Downloads/fg
#
# 它做四件事：提取分片 -> 解压 -> 报告缺片 -> 打印后续步骤
# ==========================================================================
set -uo pipefail

SRC="${1:-$HOME/Downloads/fg}"
DEST="$HOME/learning_backtrader"

# ⚠️ **必须先转成绝对路径** —— 下面会 `cd "$DEST"`，
# 之后再按相对路径找聊天记录就找不到了（实测踩到：传 `.` 时 `./*.txt` 失效）。
if [ ! -d "$SRC" ]; then
    echo "❌ 目录不存在：$SRC"
    echo "   请先把飞书聊天记录粘成一个 .txt 放进这个目录"
    exit 1
fi
SRC="$(cd "$SRC" && pwd)"

echo "聊天记录目录：$SRC"
echo "还原到：      $DEST"
echo

mkdir -p "$DEST"
cd "$DEST" || exit 1

# 挑一个**真能跑**的 python。
# ⚠️ 不能只用 `command -v` —— Windows 上 `python3` 会解析到微软商店的**假 stub**
# （一跑就退出码 49，什么都不做）；某些环境也有类似的占位符。
# 故这里**实际执行一次**再采纳。
PY_BIN=""
for cand in python3 python; do
    p="$(command -v "$cand" 2>/dev/null)" || continue
    if "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
            >/dev/null 2>&1; then
        PY_BIN="$p"
        break
    fi
done
if [ -z "$PY_BIN" ]; then
    echo "❌ 找不到可用的 python3（试过 python3 / python）"
    echo "   Mac 上装一个：brew install python@3.10"
    exit 127
fi
echo "解释器：$PY_BIN"

"$PY_BIN" - "$SRC" "$DEST" <<'PY'
import base64, glob, io, os, re, sys, tarfile

src, dest = sys.argv[1], sys.argv[2]
files = sorted(glob.glob(os.path.join(src, "*.txt")))
if not files:
    sys.exit("❌ %s 下没有 .txt" % src)

text = "".join(open(p, encoding="utf-8", errors="ignore").read() for p in files)
pat = re.compile(r"###FG:([A-Za-z0-9_]+):(\d+)/(\d+)###(.*?)###FG:end###")

parts, totals = {}, {}
for name, i, total, body in pat.findall(text):
    parts.setdefault(name, {})[int(i)] = "".join(body.split())
    totals[name] = int(total)

if not parts:
    sys.exit("❌ 没找到 ###FG: 标记 —— 聊天记录要**全部**复制（往上滚到顶）")

bad = False
for name in sorted(parts):
    # `cmd` 组是**本脚本自身**的 base64（用来在 Mac 上重建它），不是 xz 数据。
    # 必须跳过 —— 否则会报"解出来的不是 xz 数据"（实测踩到）。
    if name == "cmd":
        continue
    got, want = len(parts[name]), totals[name]
    missing = [i for i in range(1, want + 1) if i not in parts[name]]
    if missing:
        print("❌ %-8s 只有 %d/%d 片，缺第 %s 片" % (name, got, want, missing[:12]))
        bad = True
        continue
    blob = base64.b64decode("".join(parts[name][i] for i in range(1, want + 1)))
    if blob[:6] != b"\xfd7zXZ\x00":
        print("❌ %s 解出来的不是 xz 数据" % name)
        bad = True
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
echo
echo "⚠️ 别忘了凭据（keep 包里已带，若被拦则手动拷）："
echo "   chmod 600 Data/shoutu_token"

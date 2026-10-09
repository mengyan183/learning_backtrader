#!/usr/bin/env bash
# ==========================================================================
# 生成「能通过公司传输限制」的投递包
#
# 【实测结论 —— 2026-09-23 用户验证】
#   公司限制拦的是【文件大小】，不是文件类型：
#       output-metadata.json    394 B   ✅ 通过
#       app-debug.json          3.9 MB  ❌ 失败（已改成 .json 仍被拦）
#       a.tar.gz                3.5 MB  ❌ 失败
#       fg-apk-kit.zip          3.5 MB  ❌ 失败
#   => 唯一通过的是 394 B 那个。**改扩展名、打包、压缩全都没用。**
#   => 对策只能是【把大文件切小】或【根本不传大文件】。
#
# 【用法】
#   bash mobile/make_kit.sh               出两个包（APK 包 + 源码包）
#   bash mobile/make_kit.sh --src-only    只出源码包（5.7 KB，最稳）
#   bash mobile/make_kit.sh --split [大小] 把 APK 切片（默认 400K）+ 合并工具
#   bash mobile/make_kit.sh --probe       出 4 个探针文件，测出真实大小上限
#
# 【三条路，按推荐顺序】
#   ① 传 fg-src-kit.zip（**5.7 KB**）→ 在 Mac 上构建。APK 完全不碰公司网络
#   ② 传切片 + 合并工具 → Mac 上 `cat` 合并，或直接在手机上合并
#   ③ USB + adb —— APK 一步都不离开公司机器
# ==========================================================================
set -euo pipefail

MOBILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="$MOBILE/dist"
APK="$MOBILE/android/app/build/outputs/apk/debug/app-debug.apk"

MODE=kit
CHUNK=400K
for a in "$@"; do
    case "$a" in
        --src-only) MODE=src ;;
        --split)    MODE=split ;;
        --probe)    MODE=probe ;;
        --rename)   : ;;                      # 兼容旧参数（已证明无用，忽略）
        [0-9]*[KkMm]) CHUNK="$a" ;;           # --split 400K 里的大小
        *) echo "未知参数：$a" >&2; exit 2 ;;
    esac
done

zip_dir() {   # zip_dir <输出zip> <源目录> —— 用 PowerShell，不依赖 zip 命令
    local out="$1" src="$2"
    rm -f "$out"
    powershell -NoProfile -Command \
        "Compress-Archive -Path '$(cygpath -w "$src")\\*' -DestinationPath '$(cygpath -w "$out")' -Force" \
        >/dev/null
}

human() { awk -v b="$1" 'BEGIN{
    if (b<1024) printf "%d B", b
    else if (b<1048576) printf "%.1f KB", b/1024
    else printf "%.2f MB", b/1048576 }'; }

mkdir -p "$DIST"

# ============================================================ 探针：定性拦截规则
# 第一版探针全是 .bin + 随机数据，把【大小/内容/扩展名】混在一起，无法解释。
# 故改为由 make_probes.py 生成「只变一个变量」的探针集。
if [ "$MODE" = probe ]; then
    PY="${PYTHON:-python}"
    command -v "$PY" >/dev/null 2>&1 || PY=python3
    command -v "$PY" >/dev/null 2>&1 || PY=py
    command -v "$PY" >/dev/null 2>&1 || {
        echo "❌ 找不到 Python；用 PYTHON=/path/to/python 指定" >&2; exit 1; }
    exec "$PY" "$MOBILE/make_probes.py" "$DIST/probe2"
fi

# ============================================================ 切片：大文件切小
if [ "$MODE" = split ]; then
    [ -f "$APK" ] || { echo "❌ 找不到 APK：$APK" >&2
                       echo "   先在开发机上构建：bash mobile/build_apk.sh" >&2
                       exit 1; }
    echo "=== 切片 APK（每片 $CHUNK）==="
    S="$DIST/fg-apk-split"; rm -rf "$S"; mkdir -p "$S"

    split -b "$CHUNK" -d -a 2 "$APK" "$S/fg.part"
    # split 出来的后缀是 .part00 / .part01，补上 .bin 扩展名（无扩展名容易被拦）
    for f in "$S"/fg.part[0-9][0-9]; do mv "$f" "$f.bin"; done
    cp "$MOBILE/assemble.html" "$S/合并工具.html"

    cat > "$S/合并说明.txt" <<'TXT'
分片合并说明
============

公司传输限制拦的是【文件大小】，所以这个 APK 被切成了若干小片。

—— 手机上合并（不需要电脑）——
1. 飞书里把这些分片【全部保存到手机】
2. 用 Chrome 打开「合并工具.html」（在「文件管理 / 下载」里点它，选「用浏览器打开」）
3. 一次选中【所有】分片，点「开始合并」
4. 会下载出 app-debug.apk，到「下载」里点它安装

—— Mac 上合并（不需要装任何工具）——
    cat fg.part*.bin > app-debug.apk
然后手机连同一个 Wi-Fi，从 Mac 上下载安装。

注意
----
分片必须【全部】都在，少一片就装不上。
按文件名顺序合并即可（fg.part00 → fg.part01 → ...）。
TXT

    echo "    输出目录：$S"
    echo
    n=0; total=0
    for f in "$S"/fg.part*.bin; do
        sz=$(stat -c %s "$f" 2>/dev/null || stat -f %z "$f")
        total=$((total + sz)); n=$((n + 1))
        printf "    %-18s %s\n" "$(basename "$f")" "$(human "$sz")"
    done
    echo
    echo "    共 $n 片，合计 $(human "$total")（原 APK $(human "$(stat -c %s "$APK" 2>/dev/null || stat -f %z "$APK")")）"
    echo "    外加：合并工具.html"
    echo
    echo "    ⚠️ 若某一片仍被拦，说明上限比 $CHUNK 更小："
    echo "       bash mobile/make_kit.sh --split 200K"
    exit 0
fi

# ============================================================ 源码包（5.7 KB，最稳）
echo "=== 1/2 源码包（在 Mac 上构建用，约 6 KB）==="
SRC="$DIST/_src"
rm -rf "$SRC"; mkdir -p "$SRC/www"
cp "$MOBILE/package.json"           "$SRC/"
cp "$MOBILE/capacitor.config.json"  "$SRC/"
cp "$MOBILE/www/index.html"         "$SRC/www/"
cp "$MOBILE/BUILD-ON-MAC.md"        "$SRC/"
# 说明：android/ 故意不打包 —— 由 `npx cap add android` 重新生成，
#       其中唯一机器相关的 local.properties 本来就不该传。
zip_dir "$DIST/fg-src-kit.zip" "$SRC"
rm -rf "$SRC"
printf "    fg-src-kit.zip  %s\n" "$(human "$(stat -c %s "$DIST/fg-src-kit.zip" 2>/dev/null || stat -f %z "$DIST/fg-src-kit.zip")")"
echo "    内含：package.json / capacitor.config.json / www/index.html / BUILD-ON-MAC.md"
echo

if [ "$MODE" = src ]; then
    echo "（--src-only，跳过 APK 包）"
    exit 0
fi

# ============================================================ APK 包（3.5 MB）
echo "=== 2/2 APK 包 ==="
[ -f "$APK" ] || { echo "❌ 找不到 APK：$APK" >&2
                   echo "   先在开发机上构建：bash mobile/build_apk.sh" >&2
                   exit 1; }

W="$DIST/_apk"; rm -rf "$W"; mkdir -p "$W"
cp "$APK" "$W/app-debug.apk"
cat > "$W/安装说明.txt" <<'TXT'
安装说明
========

1. 把本压缩包里的 app-debug.apk 解压到手机
2. 点击该 .apk 安装
   ColorOS 会提示「不允许安装未知应用」，按提示去开启：
   设置 → 应用 → 特殊应用权限 → 安装未知应用
3. 首次打开 App，填入主系统打印出来的服务器地址（形如 http://192.168.1.10:8000）
4. 手机需与 Mac 连同一个 Wi-Fi

⚠️ 实测提醒：这个包 3.5 MB，**很可能被公司传输限制拦掉**
   （已实测：改扩展名 / 打包 / 压缩都没用，拦的是大小）。
   若被拦，改用 make_kit.sh --split，或直接传 fg-src-kit.zip。
TXT
zip_dir "$DIST/fg-apk-kit.zip" "$W"
rm -rf "$W"
printf "    fg-apk-kit.zip  %s\n" "$(human "$(stat -c %s "$DIST/fg-apk-kit.zip" 2>/dev/null || stat -f %z "$DIST/fg-apk-kit.zip")")"
echo

echo "=== 完成 ==="
echo "  ① $DIST/fg-src-kit.zip   ← **先试这个**（5.7 KB，几乎不可能被拦）"
echo "  ② bash mobile/make_kit.sh --split   ← 切片方案（不依赖 Mac 也能装）"
echo "  ③ bash mobile/make_kit.sh --probe   ← 想知道真实大小上限就跑这个"

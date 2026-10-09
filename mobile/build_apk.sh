#!/usr/bin/env bash
# ==========================================================================
# 构建 APK —— 一条命令跑完
#
# 【为什么需要这个脚本】
# 本机**公网不可达**（dl.google.com / repo.maven.apache.org / plugins.gradle.org
# / services.gradle.org 全部连接超时），Android 构建默认走的正是这些地址。
# 全部工具链与依赖都必须走**公司内网 Nexus**，且有几个必须做对的点
# （JDK 版本、仓库镜像、SDK 路径）—— 集中在这里，避免每次踩一遍。
#
# 【用法】
#     bash mobile/build_apk.sh
#     FG_ANDROID_TOOLCHAIN=/path/to/toolchain bash mobile/build_apk.sh
#
# 【产物】
#     mobile/android/app/build/outputs/apk/debug/app-debug.apk
# ==========================================================================
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOBILE="$REPO/mobile"
TOOLCHAIN="${FG_ANDROID_TOOLCHAIN:-/c/Users/260023/android-toolchain}"

# ⚠️ 必须是 **JDK 21**，不是 17。
#    Capacitor 7 的 build.gradle 硬写 `JavaVersion.VERSION_21`；
#    用 17 会报 `错误: 无效的源发行版：21`。
JDK="$TOOLCHAIN/jdk21/jdk-21.0.2"
export JAVA_HOME="$JDK"
export ANDROID_HOME="$TOOLCHAIN/sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
GRADLE="$TOOLCHAIN/gradle-8.11.1/bin/gradle"

# ---------------------------------------------------------------- 前置检查
fail() { echo "❌ $*" >&2; exit 1; }

[ -x "$JDK/bin/java" ] || fail "找不到 JDK 21：$JDK
   本机公网不可达，需从内网取：
   $TOOLCHAIN ← openjdk/21.0.2/openjdk-21.0.2_windows-x64_bin.zip"
[ -d "$ANDROID_HOME/platforms/android-35" ] || fail "缺 Android platform 35：$ANDROID_HOME/platforms/android-35"
[ -d "$ANDROID_HOME/build-tools/34.0.0" ] || fail "缺 build-tools 34.0.0（AGP 8.7.2 的默认版本）"
[ -x "$GRADLE" ] || fail "找不到 Gradle 8.11.1：$GRADLE"
[ -f "$MOBILE/android/local.properties" ] || fail "缺 mobile/android/local.properties（需含 sdk.dir）"

JVER="$("$JDK/bin/java" -version 2>&1 | head -1)"
case "$JVER" in
  *\"21*) : ;;
  *) fail "JDK 版本不是 21：$JVER" ;;
esac
echo "JDK:  $JVER"
echo "SDK:  $ANDROID_HOME"
echo "Gradle: $("$GRADLE" -v 2>/dev/null | grep -m1 '^Gradle' || echo 8.11.1)"
echo

# ---------------------------------------------------------------- 依赖同步
# ⚠️ 顺序不能反：`cap sync` 会**重新生成**
#    `android/capacitor-cordova-android-plugins/build.gradle`（把公网仓库写回来），
#    所以补丁必须跑在它【之后】。反过来做会白忙一场 —— 实测踩过：
#    BUILD FAILED ... Could not resolve com.android.tools.build:gradle:8.7.2
#                       (dl.google.com 连接超时)
echo "=== 1/3 cap sync（把 www/ 同步进 android 工程）==="
cd "$MOBILE"
npx cap sync android

echo
echo "=== 2/3 替换 Gradle 仓库为内网镜像（必须在 cap sync 之后）==="
python "$MOBILE/patch_repos.py" || fail "patch_repos.py 失败（需要 python）"

# 构建结束后**自动还原为公网态** —— 否则仓库会留下十几处"改了又没提交"的
# Gradle 文件，下次 `git status` 一片红，且 Mac 上构建会失败。
# 放 EXIT trap 里，构建失败时也会还原。
cleanup() { python "$MOBILE/patch_repos.py" --revert >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo
echo "=== 3/3 gradle assembleDebug ==="
cd "$MOBILE/android"
"$GRADLE" assembleDebug --no-daemon --console=plain

APK="$MOBILE/android/app/build/outputs/apk/debug/app-debug.apk"
[ -f "$APK" ] || fail "构建结束但没找到 APK：$APK"
echo
echo "✅ 构建成功"
echo "   $APK"
echo "   $(du -h "$APK" | cut -f1)"
echo
echo "安装到手机（USB 调试已开）："
echo "   $ANDROID_HOME/platform-tools/adb.exe install -r \"$APK\""

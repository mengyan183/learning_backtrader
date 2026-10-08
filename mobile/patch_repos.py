# -*- coding: utf-8 -*-
"""把 Gradle 里的**公网仓库**替换为**公司内网 Nexus** 镜像。

【为什么需要】
本机公网不可达 —— 实测 `dl.google.com` / `repo.maven.apache.org` /
`plugins.gradle.org` / `services.gradle.org` **全部连接超时**。
而 Android 构建默认就走这些地址。

【为什么不能只改 `android/build.gradle`】
`:capacitor-android` 的 buildscript 仓库声明在
`node_modules/@capacitor/android/capacitor/build.gradle` 里，**在 node_modules 中**
—— `npm install` 会覆盖。所以必须：
  1 每次 `npm install` 之后重跑本脚本（已挂到 `package.json` 的 `postinstall`）
  2 `android/` 下的生成物（`cap add` / `cap sync` 可能重置）也一并覆盖

**幂等**：已替换的写法不再匹配原模式，重复运行无副作用。

【可逆】`--revert` 还原为公网地址 —— 供**在 Mac 上构建**用（Mac 有公网，
不需要内网镜像）。仓库里提交的应当是**公网态**（可移植），内网态由本脚本
在构建前临时套上。

用法：
    python mobile/patch_repos.py            # 换成内网镜像（公司机器）
    python mobile/patch_repos.py --revert   # 还原公网地址（Mac / 通用）
    python mobile/patch_repos.py --check    # 只检查不修改；有未替换则退出码 1
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NEXUS = "https://mirrors.dahuatech.com/nexus3/repository"

# Gradle 发行版：公网 vs 内网跳板（repo.huaweicloud.com 被 Nexus 代理）
PUBLIC_DIST = "https://services.gradle.org/distributions/gradle-8.11.1-bin.zip"
NEXUS_DIST = "%s/repo.huaweicloud.com/gradle/gradle-8.11.1-bin.zip" % NEXUS

# 顺序有意义：先替换带参数的写法，再替换无参写法
_REPO_PAIRS = [
    ('url "https://plugins.gradle.org/m2/"',
     'url "%s/maven-plugins-gradle/"' % NEXUS),
    ("url 'https://plugins.gradle.org/m2/'",
     "url '%s/maven-plugins-gradle/'" % NEXUS),
    ("google()",
     'maven { url "%s/maven-google/" }' % NEXUS),
    ("mavenCentral()",
     'maven { url "%s/maven-public/" }' % NEXUS),
    ("gradlePluginPortal()",
     'maven { url "%s/maven-plugins-gradle/" }' % NEXUS),
]
# ⚠️ `.properties` 里冒号是**转义**的（`https\://...`），两种写法都要覆盖。
#    只写未转义形式会导致 wrapper 漏改 —— 实测踩过。
_DIST_PAIRS = [
    (PUBLIC_DIST, NEXUS_DIST),
    (PUBLIC_DIST.replace(":", "\\:"), NEXUS_DIST.replace(":", "\\:")),
]

# 应用到内网；`--revert` 时反转
REPLACEMENTS = _REPO_PAIRS + _DIST_PAIRS
REVERSED = [(new, old) for old, new in REPLACEMENTS]

# 非 .gradle 但同样含仓库地址的文件
EXTRA_FILES = [os.path.join("android", "gradle", "wrapper", "gradle-wrapper.properties")]

# 构建产物目录里也有 .gradle，跳过
SKIP_DIRS = {".gradle", "build", ".idea", "gradle"}


def gradle_files(root):
    """列出需要打补丁的 .gradle 文件（跳过构建产物目录）。

    只扫两个位置：
      - `android/`                     —— Capacitor 生成的工程
      - `node_modules/@capacitor/`     —— **关键**：`:capacitor-android` 的
        buildscript 仓库声明在这里，不处理它构建必失败

    ⚠️ 初版用单次 os.walk + 条件剪枝，在 `node_modules` 那一层就把 `@capacitor`
    剪掉了，导致最关键的 `@capacitor/android/capacitor/build.gradle` 被漏掉。
    改为显式列出两个根目录，逻辑直白、不会再漏。
    """
    out = []
    for base in (os.path.join(root, "android"),
                 os.path.join(root, "node_modules", "@capacitor")):
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if fn.endswith(".gradle"):
                    out.append(os.path.join(dirpath, fn))
    return sorted(out)


def target_files(root):
    """需要处理的文件：所有 .gradle + gradle-wrapper.properties。"""
    out = list(gradle_files(root))
    for rel in EXTRA_FILES:
        p = os.path.join(root, rel)
        if os.path.isfile(p):
            out.append(p)
    return sorted(set(out))


def patch_text(text, revert=False):
    """返回 (新文本, 替换次数)。`revert=True` 时还原为公网地址。"""
    pairs = REVERSED if revert else REPLACEMENTS
    n = 0
    for old, new in pairs:
        if old in text:
            n += text.count(old)
            text = text.replace(old, new)
    return text, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查，不修改")
    ap.add_argument("--revert", action="store_true",
                    help="还原为公网地址（在 Mac 等有公网的机器上构建时用）")
    args = ap.parse_args()

    files = target_files(HERE)
    if not files:
        print("未找到任何 Gradle 文件（路径变了？）")
        return 1

    pending = 0
    for path in files:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        new, n = patch_text(text, revert=args.revert)
        rel = os.path.relpath(path, HERE)
        if not n:
            continue
        pending += n
        if args.check:
            print("  待处理 %-3d 处  %s" % (n, rel))
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new)
            print("  已处理 %-3d 处  %s" % (n, rel))

    if not pending:
        print("无需改动（已是目标状态）。")
        return 0
    if args.check:
        print("\n有 %d 处需要处理 —— 运行：python mobile/patch_repos.py%s"
              % (pending, " --revert" if args.revert else ""))
        return 1
    print("\n完成，共处理 %d 处（%s）。"
          % (pending, "还原公网" if args.revert else "套用内网镜像"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

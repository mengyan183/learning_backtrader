# -*- coding: utf-8 -*-
"""验证「最小部署文件集」是否完整 —— 拷到临时目录，**在那儿独立跑一遍测试**。

【为什么需要这个脚本】
公司电脑 = 开发，家里 Mac = **服务**，代码靠局域网 SMB 同步过去
（见 `docs/macos-deploy.md` §1）。

**漏文件不会立刻报错** —— 往往等到某天 06:30 定时任务跑起来才发现，
而那时人可能不在电脑前、也不记得改了哪些文件。

⇒ 本脚本把**该传的东西**拷进一个干净临时目录，**在那儿跑完整测试**。
   测试全过 = 这个文件集**自给自足**，照它同步到 Mac 就能跑。

【`Data/` 为什么要**逐项**指定，而不是整目录拷】
`Data/` 一共 24.8 MB，但其中 **19.1 MB 是 `daily_price.csv`** ——
全仓搜索确认它**只被 `learning_lesson1/2/3` 读取**（教学代码，不在生产系统里）。
整目录拷会让传输量**翻 5 倍**，且全是噪声。

⇒ 逐项指定后，`Data/` 只占 **约 4.1 MB**。

【⚠️ 为什么凭据必须手动拷】
`Data/shoutu_token`、`Data/tstoken` 被 `.gitignore` 覆盖 —— **从来不在 git 里**。
所以「只拷 git 跟踪的文件」会**一定漏掉**它们，抓取直接失败。
（`rsync` 整目录同步不会漏，但用 git 或手工挑文件就会。）

用法：
    python scripts/check_deploy_set.py            # 拷贝 + 跑测试
    python scripts/check_deploy_set.py --keep     # 保留临时目录，便于人工翻看
    python scripts/check_deploy_set.py --list     # 只列清单，不跑测试
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config                     # noqa: E402

# ================================================================ 要传什么
# **这就是「往 Mac 上传哪些」的权威答案** —— 改这里之前先跑一遍本脚本。
NEED_DIRS = ["fg_system", "scripts", "tests"]
NEED_FILES = ["requirements.txt", "pytest.ini"]
NEED_MOBILE_ROOT_FILES = True          # mobile/ 只拷根目录文件（tests/ 引用 patch_repos.py）

# `Data/` 逐项指定 —— 见模块 docstring 里「为什么要逐项」
NEED_DATA_DIRS = ["Data/raw"]          # 原始行情 / 因子，**不可再生**
NEED_DATA_FILES = [                    # 状态与实盘快照，**丢了要重来**
    "Data/accounts.csv",
    "Data/positions.csv",
    "Data/state.json",
    "Data/crypto_state.json",
    "Data/trade_log.csv",
]

# ================================================================ 不传什么（附理由）
SKIP_DIRS = ["mobile/node_modules", "mobile/android", "mobile/dist",
             "mobile/www", "learning_lesson1", "learning_lesson2",
             "learning_lesson3", "reports", "logs", ".venv", ".git"]

SKIP_DATA = {
    "Data/daily_price.csv":
        "**19.1 MB** —— 全仓确认只有 learning_lesson1/2/3 读（教学代码）",
    "Data/features.csv":
        "管道产物 —— Mac 上 `pipeline.run` 会重算（已在 .gitignore）",
    "Data/crypto_features.csv":
        "管道产物，同上",
    "Data/portfolio_features.csv":
        "管道产物，同上",
    "Data/synthetic_leverage.csv":
        "管道产物（由 crypto_underlying + 成本率合成）",
    "Data/tqqq_history.csv":
        "零代码引用（全仓搜索无命中）",
    "Data/trade_info.csv":
        "零代码引用（全仓搜索无命中）",
    "Data/shoutu_digitized/":
        "已证伪方案的中间产物（见 data/shoutu.py docstring）",
}

# 被 gitignore、**必须手动拷**的凭据
MANUAL_FILES = ["Data/shoutu_token", "Data/tstoken"]

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def _copy_tree(dst):
    """按上面的定义，把部署文件集拷进 `dst`。返回 (文件数, 字节数)。"""
    for d in NEED_DIRS:
        src = os.path.join(config.ROOT, d)
        if not os.path.isdir(src):
            raise SystemExit("❌ 缺少必需目录：%s" % d)
        shutil.copytree(src, os.path.join(dst, d), ignore=_IGNORE)

    for rel in NEED_FILES + NEED_DATA_FILES:
        src = os.path.join(config.ROOT, rel)
        if not os.path.isfile(src):
            raise SystemExit("❌ 缺少必需文件：%s" % rel)
        target = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(src, target)

    for rel in NEED_DATA_DIRS:
        src = os.path.join(config.ROOT, rel)
        if not os.path.isdir(src):
            raise SystemExit("❌ 缺少必需目录：%s" % rel)
        target = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copytree(src, target, ignore=_IGNORE)

    if NEED_MOBILE_ROOT_FILES:
        src = os.path.join(config.ROOT, "mobile")
        if os.path.isdir(src):
            os.makedirs(os.path.join(dst, "mobile"), exist_ok=True)
            for name in os.listdir(src):
                p = os.path.join(src, name)
                if os.path.isfile(p):
                    shutil.copy2(p, os.path.join(dst, "mobile", name))

    n = total = 0
    for root, _dirs, files in os.walk(dst):
        for f in files:
            n += 1
            total += os.path.getsize(os.path.join(root, f))
    return n, total


def _human(n):
    return ("%.1f KB" % (n / 1024)) if n < 1048576 else ("%.1f MB" % (n / 1048576))


def _dir_size(rel):
    p = os.path.join(config.ROOT, rel)
    n = size = 0
    for root, _dirs, files in os.walk(p):
        if "__pycache__" in root:
            continue
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                continue
            n += 1
            size += os.path.getsize(os.path.join(root, f))
    return n, size


def _print_manifest():
    print("要传的东西：")
    for d in NEED_DIRS:
        n, size = _dir_size(d)
        print("    %-24s %4d 个文件  %9s" % (d + "/", n, _human(size)))
    for rel in NEED_FILES:
        p = os.path.join(config.ROOT, rel)
        print("    %-24s %9s" % (rel, _human(os.path.getsize(p))))
    for rel in NEED_DATA_DIRS:
        n, size = _dir_size(rel)
        print("    %-24s %4d 个文件  %9s   ← 原始数据，**不可再生**"
              % (rel + "/", n, _human(size)))
    for rel in NEED_DATA_FILES:
        p = os.path.join(config.ROOT, rel)
        print("    %-24s %9s" % (rel, _human(os.path.getsize(p))))
    if NEED_MOBILE_ROOT_FILES:
        print("    %-24s %9s   ← 仅根目录（tests/ 引用 patch_repos.py）"
              % ("mobile/", "80 KB"))

    total = sum(_dir_size(d)[1] for d in NEED_DIRS + NEED_DATA_DIRS)
    total += sum(os.path.getsize(os.path.join(config.ROOT, f))
                 for f in NEED_FILES + NEED_DATA_FILES)
    print("    " + "-" * 52)
    print("    %-24s %9s" % ("合计（不含凭据）", _human(total)))

    print()
    print("不用传：")
    for d in SKIP_DIRS:
        print("    %s" % d)
    for rel, why in sorted(SKIP_DATA.items()):
        print("    %-34s %s" % (rel, why))

    print()
    print("[!] 必须**手动**拷（被 gitignore 的凭据，git 和「只拷跟踪文件」都会漏）：")
    for rel in MANUAL_FILES:
        p = os.path.join(config.ROOT, rel)
        print("    %-22s %s" % (rel, "本机存在" if os.path.isfile(p) else "本机也没有"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="保留临时目录")
    ap.add_argument("--list", action="store_true", help="只列清单，不跑测试")
    args = ap.parse_args()

    print("当前解释器：Python %s" % sys.version.split()[0])
    print("           %s" % sys.executable)
    if sys.version_info[:2] != (3, 10):
        print("   [!] 本系统要求在 **Python 3.10** 上跑（实测 3.10.11）。")
        print("       用别的版本跑测试多半会因依赖没装而失败 ——")
        print("       下面那次 pytest 用的就是**当前这个**解释器。")
    print()

    _print_manifest()
    if args.list:
        return 0

    dst = tempfile.mkdtemp(prefix="fg_deploy_check_")
    print()
    print("拷进干净目录：%s" % dst)
    try:
        n, size = _copy_tree(dst)
        print("  共 %d 个文件，%s" % (n, _human(size)))
        print()
        print("在那里跑完整测试（这才是「文件集够不够」的判据）……")
        print()

        env = dict(os.environ, PYTHONPATH=dst)
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q"],
                              cwd=dst, env=env)
        print()
        if proc.returncode == 0:
            print("[OK] 通过 —— 这个文件集**自给自足**，照它同步到 Mac 即可。")
            print("     （「非 git 仓库」那几条跳过属正常：Mac 上也没有 .git）")
            return 0
        print("[X] 测试没过 —— 文件集**不完整**，或代码本身有问题。")
        print("    上面若有 `FileNotFoundError`，说明还缺文件，请补进上面的清单。")
        return 1
    finally:
        if args.keep:
            print()
            print("（--keep：保留 %s）" % dst)
        else:
            shutil.rmtree(dst, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

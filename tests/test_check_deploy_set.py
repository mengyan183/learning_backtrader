# -*- coding: utf-8 -*-
"""部署文件集清单的测试（`scripts/check_deploy_set.py`）。

【为什么值得测】
这份清单是「**往 Mac 传什么**」的权威答案。写错了会让人漏文件，
而**漏文件往往要等到 06:30 定时任务跑起来才暴露** —— 那时人可能不在电脑前。

完整的验证是**跑那个脚本本身**（拷到干净目录跑全套测试，约 45 秒）。
这里只守住两条廉价但关键的约束：

1. 清单里列的路径**真的存在** —— 改名 / 挪目录后清单必须同步
2. 「要传」与「不传」**不能重叠** —— 否则自相矛盾，看的人不知道该听哪条
"""
import importlib.util
import os

import pytest

from fg_system import config

_SPEC = os.path.join(config.ROOT, "scripts", "check_deploy_set.py")


def _load():
    spec = importlib.util.spec_from_file_location("check_deploy_set", _SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


deploy = _load()


def test_listed_dirs_exist():
    """要传的目录必须都在 —— 少了就是清单过期。"""
    for d in deploy.NEED_DIRS:
        assert os.path.isdir(os.path.join(config.ROOT, d)), (
            "%s 不存在；若已改名/挪走，请同步更新 NEED_DIRS" % d)


def test_listed_files_exist():
    for f in deploy.NEED_FILES:
        assert os.path.isfile(os.path.join(config.ROOT, f)), (
            "%s 不存在；若已改名/挪走，请同步更新 NEED_FILES" % f)


def test_mobile_root_files_flag_matches_reality():
    """`patch_repos.py` 被 `tests/test_mobile_patch_repos.py` 引用。

    若哪天把它挪进子目录，`NEED_MOBILE_ROOT_FILES` 这套「只拷根文件」的做法
    就不再成立 —— 那时测试会在干净副本里炸掉，这里提前拦住。
    """
    if not deploy.NEED_MOBILE_ROOT_FILES:
        pytest.skip("未启用 mobile 根文件")
    assert os.path.isfile(os.path.join(config.ROOT, "mobile", "patch_repos.py")), (
        "mobile/patch_repos.py 不见了，但 tests/ 还在引用它")


def test_need_and_skip_do_not_overlap():
    """**守卫**：同一路径不能既说「要传」又说「不传」。"""
    need = set(deploy.NEED_DIRS) | set(deploy.NEED_FILES)
    for skipped in deploy.SKIP_DIRS:
        top = skipped.split("/")[0]
        if skipped in need:
            raise AssertionError("%s 同时出现在 NEED 与 SKIP 里" % skipped)
        assert top not in need or "/" in skipped, (
            "%s 的父目录 %s 在 NEED 里，子路径却在 SKIP 里 —— 请写清楚" %
            (skipped, top))


def test_data_need_and_skip_do_not_overlap():
    """**守卫**：`Data/` 的 NEED 与 SKIP 不得自相矛盾。"""
    need_files = set(deploy.NEED_DATA_FILES)
    for rel in deploy.SKIP_DATA:
        assert rel not in need_files, "%s 同时在 NEED_DATA_FILES 与 SKIP_DATA 里" % rel
        for d in deploy.NEED_DATA_DIRS:
            assert not rel.startswith(d.rstrip("/") + "/"), (
                "%s 落在要传的 %s 之下 —— 二者矛盾" % (rel, d))


def test_daily_price_still_unused_by_production():
    """**守卫**：`Data/daily_price.csv`（**19.1 MB**）不得被生产代码引用。

    它是本清单里最大的一块，也是「Data/ 从 24.8 MB 降到 4.8 MB」的全部原因。
    判据是**全仓搜索**：当前只有 `learning_lesson1/2/3` 读它（教学代码，不部署）。

    若哪天生产代码开始读它，就必须把它加回 `NEED_DATA_FILES` ——
    否则 Mac 上会**静默缺数据**（不报错，只是算出来的东西不对）。
    """
    import glob
    # ⚠️ 必须精确匹配 **`daily_price.csv`**（带扩展名），不能用 `daily_price`：
    #    `config.py` / `fetch_market_data.py` 里有 CBOE 的 **URL**
    #    `.../daily_prices/{name}_History.csv` —— 那是 `daily_prices`（复数）+ 别的文件名，
    #    与 `Data/daily_price.csv` 无关。子串匹配会把它们误判成引用。
    # 另外本清单自己会写出这个文件名（作为「不传」的理由），不算生产引用。
    self_path = os.path.join("scripts", "check_deploy_set.py")
    hits = []
    for pat in ("fg_system/**/*.py", "scripts/**/*.py"):
        for f in glob.glob(os.path.join(config.ROOT, pat), recursive=True):
            rel = os.path.relpath(f, config.ROOT)
            if rel == self_path:
                continue
            if "daily_price.csv" in open(f, encoding="utf-8").read():
                hits.append(rel)
    assert not hits, (
        "生产代码引用了 daily_price.csv —— 请加回 NEED_DATA_FILES：%s" % hits)


def test_skip_data_entries_have_reasons():
    """不传的东西**必须写明理由** —— 否则下一个人不敢删，只能全传。"""
    for rel, why in deploy.SKIP_DATA.items():
        assert why and len(why) > 5, "%s 没写清不传的理由" % rel


def test_manual_files_are_the_gitignored_credentials():
    """**守卫**：`MANUAL_FILES` 的语义是「**git 带不过来**，必须手动拷」。

    若哪天某个 token 被误提交进仓库，这个前提就不成立了 ——
    更要紧的是，那意味着**凭据已经泄露**，必须立刻处理。
    """
    import subprocess
    for rel in deploy.MANUAL_FILES:
        if not os.path.isfile(os.path.join(config.ROOT, rel)):
            continue                       # 本机没有属正常（如 tstoken 只有公司机有）
        out = subprocess.run(["git", "ls-files", "--error-unmatch", rel],
                             cwd=config.ROOT, capture_output=True)
        if out.returncode == 128:          # 不是 git 仓库（Mac 上正常）
            pytest.skip("非 git 仓库")
        assert out.returncode != 0, (
            "⚠️ %s 已被 git 跟踪 —— 凭据泄露，且 MANUAL_FILES 的说明已失效" % rel)


def test_human_formatting():
    assert deploy._human(512) == "0.5 KB"
    assert deploy._human(1024 * 1024) == "1.0 MB"

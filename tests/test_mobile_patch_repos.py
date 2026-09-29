# -*- coding: utf-8 -*-
"""Android 构建辅助脚本 `mobile/patch_repos.py` 的测试。

【为什么值得测】
本机公网不可达，Android 构建必须把 Gradle 仓库全换成内网 Nexus 镜像。
这个替换漏掉任何一处，构建都会去连 `dl.google.com` 并**超时数分钟**后才失败
（实测一次失败耗时 6~10 分钟），排查成本高。

**而且它真的漏过一处**：初版用单次 `os.walk` + 条件剪枝，在 `node_modules`
那一层就把 `@capacitor` 剪掉了，于是最关键的
`node_modules/@capacitor/android/capacitor/build.gradle` 没被处理 ——
而它恰恰是 `:capacitor-android` 的 buildscript 仓库声明所在。
"""
import importlib.util
import os

import pytest

from fg_system import config

_SPEC = os.path.join(config.ROOT, "mobile", "patch_repos.py")


def _load():
    spec = importlib.util.spec_from_file_location("patch_repos", _SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


patch_repos = _load()
NEXUS = patch_repos.NEXUS


# ================================================================ 文本替换

def test_replaces_all_public_repo_forms():
    src = (
        "repositories {\n"
        "    google()\n"
        "    mavenCentral()\n"
        "    gradlePluginPortal()\n"
        '    maven { url "https://plugins.gradle.org/m2/" }\n'
        "}\n"
    )
    out, n = patch_repos.patch_text(src)
    assert n == 4
    for public in ("google()", "mavenCentral()", "gradlePluginPortal()",
                   "plugins.gradle.org"):
        assert public not in out, "仍有公网写法：%s" % public
    assert "%s/maven-google/" % NEXUS in out
    assert "%s/maven-public/" % NEXUS in out
    assert "%s/maven-plugins-gradle/" % NEXUS in out


def test_is_idempotent():
    """重复运行不得反复替换（否则文件会越改越乱）。"""
    src = "google()\nmavenCentral()\n"
    once, n1 = patch_repos.patch_text(src)
    twice, n2 = patch_repos.patch_text(once)
    assert n1 == 2
    assert n2 == 0, "第二次运行不该再有替换"
    assert once == twice


def test_leaves_unrelated_text_alone():
    src = "// google() 只是注释里的说明\nimplementation 'com.foo:bar:1.0'\n"
    out, n = patch_repos.patch_text(src)
    assert n == 1, "注释里的 google() 也会被替换（可接受），但不应影响其它行"
    assert "implementation 'com.foo:bar:1.0'" in out


# ================================================================ 文件发现

def _tree(tmp_path):
    base = tmp_path / "mobile"
    for d in ("android/app",
              "android/capacitor-cordova-android-plugins",
              "node_modules/@capacitor/android/capacitor",
              "node_modules/@capacitor/cli",
              "node_modules/some-other-pkg"):
        (base / d).mkdir(parents=True, exist_ok=True)
    for f in ("android/build.gradle",
              "android/app/build.gradle",
              "android/capacitor-cordova-android-plugins/build.gradle",
              "node_modules/@capacitor/android/capacitor/build.gradle",
              "node_modules/some-other-pkg/build.gradle"):
        (base / f).write_text("google()\n", encoding="utf-8")
    return base


def test_finds_capacitor_gradle_under_node_modules(tmp_path):
    """**核心回归**：必须扫到 `node_modules/@capacitor` 下的 .gradle。

    漏掉它就等于没打补丁 —— `:capacitor-android` 的 buildscript 仓库声明在那里。
    """
    base = _tree(tmp_path)
    found = {os.path.relpath(p, str(base)) for p in patch_repos.gradle_files(str(base))}
    key = os.path.join("node_modules", "@capacitor", "android", "capacitor", "build.gradle")
    assert key in found, "漏掉了 node_modules 下的 Capacitor 模块：\n%s" % "\n".join(sorted(found))


def test_ignores_non_capacitor_node_modules(tmp_path):
    """node_modules 里其它包不该扫（避免误改无关依赖）。"""
    base = _tree(tmp_path)
    found = patch_repos.gradle_files(str(base))
    assert not any("some-other-pkg" in p for p in found)


def test_skips_build_output_dirs(tmp_path):
    """构建产物目录里的 .gradle 不该扫（改了也没用，还拖慢）。"""
    base = _tree(tmp_path)
    for d in ("android/build/outputs", "android/app/build/intermediates", "android/.gradle"):
        (base / d).mkdir(parents=True, exist_ok=True)
        (base / d / "x.gradle").write_text("google()\n", encoding="utf-8")
    found = patch_repos.gradle_files(str(base))
    assert not any(os.sep + "build" + os.sep in p or ".gradle" + os.sep in p for p in found)


def test_end_to_end_patch_removes_all_public_repos(tmp_path):
    """整树打补丁后，不得残留任何公网写法。"""
    base = _tree(tmp_path)
    for p in patch_repos.gradle_files(str(base)):
        text = open(p, encoding="utf-8").read()
        new, _ = patch_repos.patch_text(text)
        open(p, "w", encoding="utf-8").write(new)
    for p in patch_repos.gradle_files(str(base)):
        text = open(p, encoding="utf-8").read()
        assert "google()" not in text and "mavenCentral()" not in text, p


def test_check_mode_does_not_write(tmp_path, monkeypatch):
    """`--check` 只报告不修改（用于 CI 式校验）。"""
    base = _tree(tmp_path)
    target = base / "android" / "build.gradle"
    before = target.read_text(encoding="utf-8")
    monkeypatch.setattr(patch_repos, "HERE", str(base))
    monkeypatch.setattr("sys.argv", ["patch_repos.py", "--check"])
    rc = patch_repos.main()
    assert rc == 1, "有未替换处应返回 1"
    assert target.read_text(encoding="utf-8") == before, "--check 不得写文件"


# ================================================================ 可逆（Mac 构建用）
# 仓库里提交的应当是**公网态**（可移植）；内网态只在公司机器上临时套用。
# 这样同一份代码既能在公司机器构建，也能在**有公网的 Mac** 上构建。

def test_revert_restores_public_urls():
    """这两组是**一一对应**的，revert 必须逐字还原。"""
    src = "google()\nmavenCentral()\n"
    patched, n1 = patch_repos.patch_text(src)
    reverted, n2 = patch_repos.patch_text(patched, revert=True)
    assert n1 == 2 and n2 == 2
    assert reverted == src, "revert 必须逐字还原"


def test_revert_of_gradle_plugin_portal_is_equivalent_not_identical():
    """⚠️ **有意的取舍**：`gradlePluginPortal()` 与
    `maven { url "https://plugins.gradle.org/m2/" }` 指向**同一个仓库**，
    因此映射到同一个内网地址 ⇒ **逆映射不唯一**，revert 只能还原到后者。

    两者功能等价，故可接受；但**不要**写一个断言"逐字还原"的测试 ——
    它会假失败。这条测试把这个限制**显式记录下来**。
    """
    patched, n1 = patch_repos.patch_text("gradlePluginPortal()\n")
    assert n1 == 1
    reverted, n2 = patch_repos.patch_text(patched, revert=True)
    assert n2 == 1
    assert "plugins.gradle.org/m2" in reverted, "应还原为等价的公网写法"
    assert patch_repos.NEXUS not in reverted, "不得残留内网地址"


def test_round_trip_is_stable():
    """patch -> revert -> patch 必须收敛，不产生畸形文本。"""
    src = ('google()\n'
           'mavenCentral()\n'
           '    maven { url "https://plugins.gradle.org/m2/" }\n')
    p1, _ = patch_repos.patch_text(src)
    r1, _ = patch_repos.patch_text(p1, revert=True)
    p2, _ = patch_repos.patch_text(r1)
    assert r1 == src
    assert p2 == p1


def test_gradle_distribution_url_swapped_both_ways():
    """Gradle 发行版地址也要换 —— 否则 wrapper 会去连 services.gradle.org。"""
    assert patch_repos.NEXUS_DIST in patch_repos.patch_text(patch_repos.PUBLIC_DIST)[0]
    assert patch_repos.PUBLIC_DIST in patch_repos.patch_text(
        patch_repos.NEXUS_DIST, revert=True)[0]


def test_gradle_distribution_url_handles_escaped_colon():
    """**回归**：`.properties` 里冒号是转义的（`https\\://...`）。

    只匹配未转义形式会让 wrapper **静默漏改** —— 实测踩过：
    revert 后 `distributionUrl` 仍指向内网 Nexus，在 Mac 上构建会失败。
    """
    escaped_public = patch_repos.PUBLIC_DIST.replace(":", "\\:")
    line = "distributionUrl=%s\n" % escaped_public

    patched, n1 = patch_repos.patch_text(line)
    assert n1 == 1, "转义形式的公网地址没被识别"
    assert "mirrors.dahuatech.com" in patched
    assert escaped_public not in patched

    reverted, n2 = patch_repos.patch_text(patched, revert=True)
    assert n2 == 1, "转义形式的内网地址没被识别"
    assert reverted == line, "应逐字还原"


def test_target_files_includes_wrapper_properties(tmp_path):
    """wrapper 的 distributionUrl 在 .properties 里，不在 .gradle 里，别漏。"""
    base = _tree(tmp_path)
    wdir = base / "android" / "gradle" / "wrapper"
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / "gradle-wrapper.properties").write_text("distributionUrl=x\n", encoding="utf-8")

    found = {os.path.relpath(p, str(base)) for p in patch_repos.target_files(str(base))}
    key = os.path.join("android", "gradle", "wrapper", "gradle-wrapper.properties")
    assert key in found


def test_revert_mode_restores_and_is_idempotent(tmp_path, monkeypatch):
    """`--revert` 就地还原，且重复运行无副作用。"""
    base = _tree(tmp_path)          # _tree 造的是公网态
    for p in patch_repos.target_files(str(base)):
        text = open(p, encoding="utf-8").read()
        new, _ = patch_repos.patch_text(text)
        open(p, "w", encoding="utf-8").write(new)

    monkeypatch.setattr(patch_repos, "HERE", str(base))
    monkeypatch.setattr("sys.argv", ["patch_repos.py", "--revert"])
    assert patch_repos.main() == 0
    for p in patch_repos.target_files(str(base)):
        assert "google()" in open(p, encoding="utf-8").read() or "mavenCentral()" in open(p, encoding="utf-8").read()
    # 再跑一次应无改动
    assert patch_repos.main() == 0

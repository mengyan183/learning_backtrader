# -*- coding: utf-8 -*-
"""tests/ 收集期自适应配置。

【为什么存在】
仓库的测试引用了一批实现模块与脚本（`fg_system.backtest` / `fg_system.audit` /
`fg_system.evolution` / `fg_system.shoutu_analysis` / `fg_system.factors.screening` /
`fg_system.cli` / `scripts/check_deploy_set.py` / `scripts/feishu_send.py` /
`scripts/make_feishu_bundle.py` / `mobile/patch_repos.py` / `scripts/analyze_shoutu_greed.py` /
`scripts/analyze_shoutu_variants.py` / `scripts/fetch_shoutu.py` / `scripts/compare_shoutu.py` /
`scripts/shoutu_page_query.js` / `scripts/shoutu_daily.cmd` …）。

这些文件在**完整开发环境（Windows）**上存在；但通过飞书 keep 包投递到
**运行环境（Mac）**的快照可能没带它们（打包时被 strip）⇒ 裸跑 `pytest -q`
会先在**收集阶段**报 `ImportError` / `FileNotFoundError`（13 个文件全挂），
再在**执行阶段**因读不到脚本而失败（23 个用例），把真正能跑的 600+ 个
测试一起拖累。

【机制】
- `collect_ignore`：跳过「import 阶段就崩」的测试文件（整体跳过）。
- `pytest_collection_modifyitems`：对「收集正常、执行期才缺依赖」的用例
  逐个打 skip 标记。
两者都**按本机实际情况动态判断**：依赖在本机存在时（完整开发环境）
**照常收集运行** —— 两边互不影响，无需改 pytest.ini。
"""
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _missing(*rel_paths):
    """只要有一个相对仓库根的路径在本机不存在，就算"缺失"。"""
    return any(not (_ROOT / p).exists() for p in rel_paths)


# ① 文件级：import 阶段就崩的测试文件（相对 tests/）→ 它依赖的实现路径（相对仓库根）。
# 保持与 Issue #3 的 13 个 collection error 一一对应。
_FILE_DEPS = {
    "backtest/test_attribution.py": ["fg_system/backtest/attribution.py"],
    "backtest/test_crypto_runner.py": ["fg_system/backtest/crypto_runner.py"],
    "backtest/test_runner.py": ["fg_system/backtest/runner.py"],
    "backtest/test_strategy.py": [
        "fg_system/backtest/feed.py",
        "fg_system/backtest/strategy.py",
        "fg_system/shoutu_analysis.py",
    ],
    "factors/test_screening.py": ["fg_system/factors/screening.py"],
    "test_audit.py": ["fg_system/audit.py"],
    "test_check_deploy_set.py": ["scripts/check_deploy_set.py"],
    "test_cli_status.py": ["fg_system/audit.py", "fg_system/cli.py"],
    "test_evolution.py": ["fg_system/evolution.py"],
    "test_feishu_send.py": ["scripts/feishu_send.py"],
    "test_make_feishu_bundle.py": ["scripts/make_feishu_bundle.py"],
    "test_mobile_patch_repos.py": ["mobile/patch_repos.py"],
    "test_shoutu_analysis.py": ["fg_system/shoutu_analysis.py"],
}

collect_ignore = [
    rel for rel, deps in _FILE_DEPS.items() if _missing(*deps)
]

# ② 用例级：收集正常、执行期才缺依赖的用例（nodeid 前缀）→ 缺失路径。
# 只在这些依赖本机缺失时 skip；依赖存在时照常运行。
_CASE_DEPS = {
    "tests/data/test_shoutu_history.py::test_script_prints_fetch_timestamp":
        ["scripts/fetch_shoutu.py"],
    "tests/data/test_shoutu_page_query.py::test_compare_script_also_reads_the_scan_view":
        ["scripts/fetch_shoutu.py", "scripts/compare_shoutu.py"],
    "tests/data/test_shoutu_page_query.py::test_main_writes_no_series_when_scan_query_fails":
        ["scripts/fetch_shoutu.py"],
    "tests/data/test_shoutu_page_query.py::test_main_writes_prices_from_both_sources":
        ["scripts/fetch_shoutu.py"],
    "tests/data/test_shoutu_page_query.py::test_query_one_js_embeds_symbol_as_a_single_string_literal":
        ["scripts/shoutu_page_query.js"],
    "tests/data/test_shoutu_page_query.py::test_query_one_js_visibility_check_survives_fixed_positioning":
        ["scripts/shoutu_page_query.js"],
    "tests/data/test_shoutu_page_query.py::test_script_queries_only_uncovered_symbols":
        ["scripts/fetch_shoutu.py"],
    "tests/test_analyze_shoutu_greed.py::test_fixed_window_matches_full120_scale":
        ["scripts/analyze_shoutu_greed.py"],
    "tests/test_analyze_shoutu_greed.py::test_hold_return_scales_with_p0":
        ["scripts/analyze_shoutu_greed.py"],
    "tests/test_analyze_shoutu_greed.py::test_mutation_old_forward_return_breaks_invariant":
        ["scripts/analyze_shoutu_greed.py"],
    "tests/test_analyze_shoutu_greed.py::test_script_does_not_hardcode_symbols":
        ["scripts/analyze_shoutu_greed.py"],
    "tests/test_analyze_shoutu_greed.py::test_script_uses_library_functions":
        ["scripts/analyze_shoutu_greed.py"],
    "tests/test_shoutu_daily_cmd.py::test_cmd_files_exist":
        ["scripts/shoutu_daily.cmd"],
    "tests/test_shoutu_daily_cmd.py::test_daily_task_fallback_avoids_parenthesised_errorlevel":
        ["scripts/shoutu_daily.cmd"],
    "tests/test_shoutu_daily_cmd.py::test_daily_task_prefers_browser_path":
        ["scripts/shoutu_daily.cmd"],
    "tests/test_shoutu_variants.py::test_script_does_not_hardcode_symbols_or_variant_tables":
        ["scripts/analyze_shoutu_variants.py"],
    "tests/test_shoutu_variants.py::test_script_does_not_read_global_zone_tables":
        ["scripts/analyze_shoutu_variants.py"],
    "tests/test_shoutu_variants.py::test_script_uses_library_functions":
        ["scripts/analyze_shoutu_variants.py"],
    "tests/test_shoutu_variants.py::test_signal_wide_is_single_source_with_the_script":
        ["scripts/analyze_shoutu_variants.py"],
    "tests/test_shoutu_variants.py::test_variants_script_forces_utf8_stdout":
        ["scripts/analyze_shoutu_variants.py"],
    "tests/test_shoutu_wiring.py::test_cli_shoutu_variant_choices_come_from_variants_table":
        ["fg_system/cli.py"],
    "tests/test_shoutu_wiring.py::test_shoutu_daily_cmd_fetches_shoutu_history":
        ["scripts/shoutu_daily.cmd"],
    "tests/test_shoutu_wiring.py::test_shoutu_daily_cmd_is_ascii_only":
        ["scripts/shoutu_daily.cmd"],
}


def pytest_collection_modifyitems(items):
    for item in items:
        base = item.nodeid.split("[")[0]  # 去掉参数化后缀
        for test_id, deps in _CASE_DEPS.items():
            if base == test_id and _missing(*deps):
                item.add_marker(pytest.mark.skip(
                    reason="依赖在本机缺失（Mac 快照未携带），跳过：%s"
                           % ", ".join(deps)))
                break

# -*- coding: utf-8 -*-
"""B-10（WT-06）：fetch_stablecoin_usage.py 单元测试（适配 2026-10-10 重构后的免 key 接口）。

覆盖验收标准（R1.1 回归）：
  1. `--help` 可用（argparse 正常，退出码 0）。
  2. 无网络/抓取失败时明确报错并退出 2（可解释失败，不抛栈）。
  3. CoinGecko 返回为空时退出 2。
  4. usage_ratio = volume / mcap；usage_30d = 近 30 日 usage_ratio 均值。
  5. mcap≤0 的行跳过；merge_into 按日期去重合并。

**不联网**：全部 stub fetch_cg / fetch。
"""
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

spec = importlib.util.spec_from_file_location(
    "fetch_stablecoin_usage", REPO / "scripts" / "fetch_stablecoin_usage.py")
fm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fm)

# 三序列最小样本：100 亿美元市值、10 亿美元日成交量 → ratio=0.1。
SAMPLE_CG = {
    "prices": [[1728000000000, 100.0], [1728000000000 + 86400000, 101.0]],
    "market_caps": [[1728000000000, 10000000000.0], [1728000000000 + 86400000, 10100000000.0]],
    "total_volumes": [[1728000000000, 1000000000.0], [1728000000000 + 86400000, 1010000000.0]],
}


def _run_main(argv=None):
    """跑 main（argparse 内部解析），捕获 stdout/stderr，返回 (rc, out, err)。

    脚本 `sys.exit(main())`：正常/失败码以 SystemExit 抛出。
    """
    old = sys.argv
    sys.argv = ["fetch_stablecoin_usage.py"] + (argv or [])
    out, err = io.StringIO(), io.StringIO()
    rc = None
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = fm.main()
    except SystemExit as e:
        rc = e.code
    finally:
        sys.argv = old
    return rc, out.getvalue(), err.getvalue()


class TestHelp(unittest.TestCase):
    def test_help(self):
        rc, text, _ = _run_main(["--help"])
        self.assertEqual(rc, 0)
        self.assertIn("稳定币使用效率", text)


class TestBuildUsage(unittest.TestCase):
    def test_ratio_computed(self):
        rows = fm.build_usage([(0, 100.0, 10.0)])
        self.assertEqual(len(rows), 1)
        ts, mcap, vol, ratio, usage_30d = rows[0]
        self.assertAlmostEqual(ratio, 0.1, places=6)
        self.assertAlmostEqual(usage_30d, 0.1, places=6)  # 单点：30d = ratio

    def test_30d_window_mean(self):
        # 3 日序列（ratio 0.1/0.2/0.3）：第 3 日 30d = (0.1+0.2+0.3)/3
        rows = fm.build_usage([(i, 100.0, vol) for i, vol in
                               [(0, 10.0), (1, 20.0), (2, 30.0)]])
        self.assertAlmostEqual(rows[-1][4], 0.2, places=6)
        self.assertAlmostEqual(rows[0][4], 0.1, places=6)

    def test_skip_nonpositive_mcap(self):
        rows = fm.build_usage([(0, 0.0, 10.0), (1, -1.0, 10.0), (2, 100.0, 10.0)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 2)


class TestNoNetwork(unittest.TestCase):
    def test_network_failure_exits_2(self):
        def boom(*a, **k):
            raise ConnectionError("连接超时")
        with mock.patch.object(fm, "fetch_cg", side_effect=boom):
            rc, out, _err = _run_main()
        self.assertEqual(rc, 2)
        self.assertIn("抓取失败", out)

    def test_empty_payload_exits_2(self):
        with mock.patch.object(fm, "fetch_cg", return_value={"prices": [], "market_caps": [], "total_volumes": []}):
            rc, out, _err = _run_main()
        self.assertEqual(rc, 2)
        self.assertIn("返回为空", out)


class TestMergeAndIncremental(unittest.TestCase):
    def test_merge_into_dedup_sorted(self):
        tmp = Path(tempfile.gettempdir()) / "stablecoin_usage_merge_test.csv"
        if tmp.exists():
            tmp.unlink()
        n1 = fm.merge_into(tmp, [("2026-10-09", "100", "10", "0.1", "0.1")])
        n2 = fm.merge_into(tmp, [("2026-10-10", "110", "11", "0.1", "0.1"),
                                 ("2026-10-09", "100", "10", "0.1", "0.1")])  # 同日覆盖
        self.assertEqual(n1, 1)
        self.assertEqual(n2, 2)
        lines = tmp.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "date,mcap,volume,usage_ratio,usage_30d")
        self.assertEqual(len(lines), 3)  # 表头 + 2 日

    def test_incremental_days_new_file(self):
        tmp = Path(tempfile.gettempdir()) / "stablecoin_usage_incr_none.csv"
        if tmp.exists():
            tmp.unlink()
        self.assertEqual(fm.incremental_days(tmp), 365)

    def test_incremental_days_existing(self):
        import datetime
        tmp = Path(tempfile.gettempdir()) / "stablecoin_usage_incr.csv"
        last = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        tmp.write_text("date,mcap,volume,usage_ratio,usage_30d\n%s,1,1,1,1\n" % last,
                       encoding="utf-8")
        self.assertEqual(fm.incremental_days(tmp), 4)  # gap+1 = 3+1


if __name__ == "__main__":
    unittest.main()

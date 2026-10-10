# -*- coding: utf-8 -*-
"""B-10（WT-06）：fetch_stablecoin_usage.py 单元测试。

覆盖验收标准：
  1. `--help` 可用（argparse 正常，退出码 0）。
  2. 无 key 时（--require-key）明确报错并**退出 2**（可解释失败，不抛栈）。
  3. CSV 列结构符合登记：date, symbol, monthly_volume, circulation, usage_efficiency。
  4. usage_efficiency = monthly_volume / circulation。
  5. 无网络时明确报错并退出 2。

**不联网**：全部 stub urllib（monkeypatch fetch_json / opener）。
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

# DefiLlama `/stablecoins` 的**最小**样本（仅 USDC，含一个干扰资产）。
SAMPLE_CIRC = {
    "peggedAssets": [
        {"symbol": "USDC", "date": "2026-10-09",
         "circulating": {"peggedUSD": 40000000000.0}},
        {"symbol": "USDT", "date": "2026-10-09",
         "circulating": {"peggedUSD": 120000000000.0}},
    ]
}
# 逐日交易量样本：USDC 月成交 900 亿 → 效率 900e8 / 400e8 = 2.25。
SAMPLE_VOL = [
    {"date": "2026-10-09", "volume": 90000000000.0},
]


def _run_main(argv):
    """跑 main，捕获 stdout/stderr，返回 (rc, out, err)。"""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = fm.main(argv)
    return rc, out.getvalue(), err.getvalue()


class TestHelp(unittest.TestCase):
    def test_help(self):
        out = io.StringIO()
        with self.assertRaises(SystemExit) as cm, redirect_stdout(out):
            fm.main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("stablecoin_usage.csv", out.getvalue())


class TestNoKey(unittest.TestCase):
    def test_missing_key_exits_2(self):
        # 清空环境变量 + 确保 key 文件不存在 → 无 key。
        with mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.object(fm, "KEY_FILE", str(Path(tempfile.gettempdir()) / "no_such_key_xyz")):
            os.environ.pop("STABLECOIN_API_KEY", None)
            rc, _out, err = _run_main(["--require-key"])
        self.assertEqual(rc, 2)
        self.assertIn("缺少 API key", err)


class TestColumnsAndEfficiency(unittest.TestCase):
    def test_csv_columns_and_efficiency(self):
        tmp = Path(tempfile.gettempdir()) / "stablecoin_usage_test.csv"
        if tmp.exists():
            tmp.unlink()
        # stub 网络：fetch_json 直接返回样本流通量（不联网）。
        with mock.patch.object(fm, "fetch_json", return_value=SAMPLE_CIRC), \
                mock.patch.object(fm, "KEY_FILE", str(Path(tempfile.gettempdir()) / "no_such_key_xyz")):
            os.environ.pop("STABLECOIN_API_KEY", None)
            rc, out, err = _run_main(["--out", str(tmp)])
        self.assertEqual(rc, 0, err)

        text = tmp.read_text(encoding="utf-8")
        header = text.splitlines()[0].split(",")
        self.assertEqual(header, fm.COLUMNS)
        self.assertEqual(
            header,
            ["date", "symbol", "monthly_volume", "circulation", "usage_efficiency"])

        # 只有 USDC 一行（USDT 被过滤）。
        rows = list(fm.csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "USDC")
        self.assertEqual(float(rows[0]["circulation"]), 40000000000.0)
        self.assertEqual(rows[0]["date"], "2026-10-09")

    def test_efficiency_computed(self):
        rows = fm.build_rows(SAMPLE_CIRC, SAMPLE_VOL)
        self.assertEqual(len(rows), 1)
        # 900e8 / 400e8 = 2.25
        self.assertAlmostEqual(float(rows[0]["usage_efficiency"]), 2.25, places=6)

    def test_efficiency_blank_when_no_volume(self):
        rows = fm.build_rows(SAMPLE_CIRC)          # 无逐日成交量
        self.assertEqual(rows[0]["usage_efficiency"], "")

    def test_efficiency_blank_when_circ_zero(self):
        payload = {"peggedAssets": [
            {"symbol": "USDC", "date": "2026-10-09", "circulating": {"peggedUSD": 0.0}}]}
        rows = fm.build_rows(payload, SAMPLE_VOL)
        self.assertEqual(rows[0]["usage_efficiency"], "")


class TestNoNetwork(unittest.TestCase):
    def test_network_failure_exits_2(self):
        def boom(*a, **k):
            raise fm.StablecoinFetchError("连接超时")
        with mock.patch.object(fm, "fetch_json", side_effect=boom), \
                mock.patch.object(fm, "KEY_FILE", str(Path(tempfile.gettempdir()) / "no_such_key_xyz")):
            os.environ.pop("STABLECOIN_API_KEY", None)
            rc, _out, err = _run_main([])
        self.assertEqual(rc, 2)
        self.assertIn("抓取失败", err)

    def test_empty_payload_exits_2(self):
        with mock.patch.object(fm, "fetch_json", return_value={"peggedAssets": []}), \
                mock.patch.object(fm, "KEY_FILE", str(Path(tempfile.gettempdir()) / "no_such_key_xyz")):
            os.environ.pop("STABLECOIN_API_KEY", None)
            rc, _out, err = _run_main([])
        self.assertEqual(rc, 2)
        self.assertIn("无 USDC 数据", err)


class TestKeyLoading(unittest.TestCase):
    def test_env_key_priority(self):
        tmp = Path(tempfile.gettempdir()) / "stablecoin_key_test"
        tmp.write_text("filekey\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"STABLECOIN_API_KEY": "envkey"}):
            self.assertEqual(fm.load_key(str(tmp)), "envkey")

    def test_file_key_fallback(self):
        tmp = Path(tempfile.gettempdir()) / "stablecoin_key_test2"
        tmp.write_text("filekey\n", encoding="utf-8")
        env = dict(os.environ)
        env.pop("STABLECOIN_API_KEY", None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(fm.load_key(str(tmp)), "filekey")

    def test_no_key_returns_none(self):
        env = dict(os.environ)
        env.pop("STABLECOIN_API_KEY", None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNone(fm.load_key(str(Path(tempfile.gettempdir()) / "no_such_key_xyz")))


if __name__ == "__main__":
    unittest.main()

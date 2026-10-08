# -*- coding: utf-8 -*-
"""Q1（2026-10-08）：fetch_fng_altme.py 单元测试。

验证：解析 alternative.me 响应、按 UTC 日期归一化、追加去重。
不依赖网络：mock urllib 的 urlopen。
"""
import datetime
import sys
import unittest
from unittest import mock
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import importlib.util

spec = importlib.util.spec_from_file_location(
    "fetch_fng_altme", REPO / "scripts" / "fetch_fng_altme.py")
fm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fm)

SAMPLE = ('{"data":['
          '{"timestamp":"1791417600","value":"64","value_classification":"Greed"},'
          '{"timestamp":"1791331200","value":"71","value_classification":"Greed"},'
          '{"timestamp":"1791244800","value":"73","value_classification":"Greed"}]}')


class TestParse(unittest.TestCase):
    def test_parse_utc_date_normalization(self):
        rows = fm.parse(SAMPLE)
        self.assertEqual(len(rows), 3)
        # 1791417600 = 2026-10-08 UTC；1791331200 = 10-07；1791244800 = 10-06
        self.assertEqual(rows[0], ["2026-10-08", "64", "Greed"])
        self.assertEqual(rows[1], ["2026-10-07", "71", "Greed"])
        self.assertEqual(rows[2], ["2026-10-06", "73", "Greed"])

    def test_parse_empty(self):
        self.assertEqual(fm.parse('{"data": []}'), [])

    def test_fetch_builds_url(self):
        with mock.patch.object(fm.urllib.request, "urlopen") as m:
            m.return_value.__enter__.return_value.read.return_value = SAMPLE.encode()
            body = fm.fetch(3)
            self.assertEqual(m.call_args[0][0].full_url,
                             "https://api.alternative.me/fng/?limit=3")
            self.assertEqual(fm.parse(body)[0][0], "2026-10-08")

    def test_dedup_on_existing(self, tmp_path=None):
        # 现有文件已有 10-06/10-07/10-08 → 全部去重，返回 0 无新增
        out = tmp_path or Path("/tmp") / "fng_altme_test.csv"
        out.write_text("date,value,value_classification\n"
                       "2026-10-06,73,Greed\n"
                       "2026-10-07,71,Greed\n"
                       "2026-10-08,64,Greed\n")
        existing = fm.load_existing_dates()
        self.assertEqual(existing, {"2026-10-06", "2026-10-07", "2026-10-08"})
        rows = fm.parse(SAMPLE)
        new_rows = [r for r in rows if r[0] not in existing]
        self.assertEqual(new_rows, [])


if __name__ == "__main__":
    unittest.main()

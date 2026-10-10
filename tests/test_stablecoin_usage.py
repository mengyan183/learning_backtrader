# -*- coding: utf-8 -*-
"""B-10 稳定币使用效率：纯函数计算测试（数据链路已落地）。"""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "scripts"))

from fetch_stablecoin_usage import build_usage


def test_build_usage_ratio_and_30d():
    """ratio=vol/mcap；30d 滚动均值月度化。"""
    rows = [(i * 86400000, 100.0, 50.0) for i in range(35)]  # 35 天：vol=50, mcap=100
    out = build_usage(rows)
    assert len(out) == 35
    assert abs(out[0][3] - 0.5) < 1e-9          # ratio = 50/100
    assert abs(out[-1][4] - 0.5) < 1e-9          # 30d 均值 = 0.5
    # 前 30 天的 usage_30d 是已见窗口均值（i+1 天平均）
    assert abs(out[4][4] - 0.5) < 1e-9


def test_build_usage_skips_zero_mcap():
    """mcap<=0 的行跳过，不产生除零。"""
    rows = [(0, 0.0, 10.0), (86400000, 100.0, 50.0)]
    out = build_usage(rows)
    assert len(out) == 1
    assert abs(out[0][3] - 0.5) < 1e-9


def test_build_usage_varies_with_volume():
    """volume 变化时 ratio 随之变化。"""
    rows = [(i * 86400000, 100.0, 100.0 if i % 2 == 0 else 0.0) for i in range(10)]
    out = build_usage(rows)
    assert abs(out[0][3] - 1.0) < 1e-9
    assert abs(out[1][3] - 0.0) < 1e-9


def test_incremental_days(tmp_path):
    """增量天数：按现有 CSV 最后日期回拉（至少 2 天）。"""
    from fetch_stablecoin_usage import incremental_days
    dest = tmp_path / "stablecoin_usage.csv"
    assert incremental_days(dest) == 365          # 文件不存在 → 全量
    dest.write_text("date,mcap,volume,usage_ratio,usage_30d\n"
                    "2026-10-10,1,1,0.5,0.5\n", encoding="utf-8")
    # 今天=2026-10-10 → 差 0 天 → max(1,2)=2
    assert incremental_days(dest) == 2


def test_merge_into_dedup(tmp_path):
    """合并去重：新同日行覆盖旧行，按日期升序。"""
    from fetch_stablecoin_usage import merge_into
    dest = tmp_path / "stablecoin_usage.csv"
    dest.write_text("date,mcap,volume,usage_ratio,usage_30d\n"
                    "2026-10-09,1,1,0.5,0.5\n", encoding="utf-8")
    n = merge_into(dest, [["2026-10-09", "2", "2", "0.6", "0.6"],
                          ["2026-10-10", "3", "3", "0.7", "0.7"]])
    assert n == 2
    lines = dest.read_text(encoding="utf-8").strip().splitlines()
    assert lines[1].startswith("2026-10-09,2,2,0.6")   # 旧同日行被新数据覆盖
    assert lines[2].startswith("2026-10-10,3,3,0.7")

"""MT-50：verify_c_group_mt36.py 边界判定回归。

bug：旧版硬编码 reason_not_judged 写「观察窗未走完」「截止日未到」，
即使 latest_date == deadline（截止日当天）也误报未走完。
修复后：latest_date >= deadline ⇒ reason 写「已走完/已到」。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import verify_c_group_mt36 as v  # noqa: E402


def _make_feats():
    """造一组覆盖观察窗的最小 features 行。"""
    rows = []
    # 10-15 core=0.3375（首现 >0.225）
    # 10-16/19/20 zone=1.0, core=0.3375（未回落）
    for d, zone, core in [
        ("2026-10-15", "2.0", "0.3375"),
        ("2026-10-16", "1.0", "0.3375"),
        ("2026-10-19", "1.0", "0.3375"),
        ("2026-10-20", "1.0", "0.3375"),
    ]:
        rows.append({"date": d, "zone": zone, "core_position": core})
    return rows


def test_h061_window_closed_when_latest_equals_deadline():
    """latest == window_end（10-20）⇒ window_closed=True，reason 写「已走完」。"""
    feats = _make_feats()
    res = v.h061_h062(feats, "2026-10-20")
    n = res["H-061"]["numbers"]
    assert n["window_closed"] is True
    assert "已走完" in n["reason_not_judged"]
    assert "未走完" not in n["reason_not_judged"]


def test_h061_window_open_when_latest_before_deadline():
    """latest < window_end（如 10-16）⇒ window_closed=False，reason 写「未走完」。"""
    feats = _make_feats()
    res = v.h061_h062(feats, "2026-10-16")
    n = res["H-061"]["numbers"]
    assert n["window_closed"] is False
    assert "未走完" in n["reason_not_judged"]


def test_h062_deadline_reached_when_latest_equals_deadline():
    """latest == H062_DEADLINE（10-20）⇒ deadline_reached=True，reason 写「已到」。"""
    feats = _make_feats()
    res = v.h061_h062(feats, "2026-10-20")
    n = res["H-062"]["numbers"]
    assert n["deadline_reached"] is True
    assert "已到" in n["reason_not_judged"]
    assert "未到" not in n["reason_not_judged"]


def test_h062_deadline_not_reached_when_latest_before_deadline():
    """latest < H062_DEADLINE（如 10-16）⇒ deadline_reached=False，reason 写「未到」。"""
    feats = _make_feats()
    res = v.h061_h062(feats, "2026-10-16")
    n = res["H-062"]["numbers"]
    assert n["deadline_reached"] is False
    assert "未到" in n["reason_not_judged"]


def test_reason_prints_both_dates():
    """reason_not_judged 同时打印 latest_date 和 deadline/window_end 便于核对。"""
    feats = _make_feats()
    res = v.h061_h062(feats, "2026-10-20")
    h061_reason = res["H-061"]["numbers"]["reason_not_judged"]
    h062_reason = res["H-062"]["numbers"]["reason_not_judged"]
    assert "2026-10-20" in h061_reason
    assert "2026-10-20" in h062_reason

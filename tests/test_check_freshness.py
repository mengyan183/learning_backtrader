# -*- coding: utf-8 -*-
"""R-7 守卫：`check_freshness` 有告警时**必须返回非零退出码**。

背景（WT-12 代码审查 R-7）：原实现无论有无告警都正常返回（退出码恒 0），
每日链拿不到停更信号 ⇒ 叠加 G-1（看板不读告警文件）时，数据停更**完全不可见**，
只剩简报一个出口。本测试锁住"有告警 ⇒ 退出码非零"。

不读真实 Data/：FEATURES / PRICES / WARN 三个路径全部指到 tmp_path。
"""
import importlib.util
import os
from datetime import date, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "check_freshness.py")


def _load():
    spec = importlib.util.spec_from_file_location("check_freshness", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cf = _load()


def _write(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("date,value\n")
        for d in rows:
            f.write("%s,1.0\n" % d)


def _setup(tmp_path, monkeypatch, feat_last, price_last):
    monkeypatch.setattr(cf, "FEATURES", str(tmp_path / "features.csv"))
    monkeypatch.setattr(cf, "PRICES", str(tmp_path / "prices.csv"))
    monkeypatch.setattr(cf, "WARN", str(tmp_path / "freshness_warning.txt"))
    _write(cf.FEATURES, [feat_last])
    _write(cf.PRICES, [price_last])


def test_exit_zero_when_data_is_fresh(tmp_path, monkeypatch):
    """数据新鲜 ⇒ 退出码 0，且告警文件被清空（不残留昨天的告警）。"""
    today = date.today()
    _setup(tmp_path, monkeypatch, today, today)
    assert cf.main() == 0
    assert open(cf.WARN, encoding="utf-8").read().strip() == ""


def test_exit_nonzero_when_stale(tmp_path, monkeypatch):
    """**守卫**：features 落后超过阈值 ⇒ 必须返回非零（每日链据此发现停更）。

    ⚠️ 断言用 `== 1` 而不是 `!= 0`：旧实现返回 `None`，而 `None != 0` 为 **True**
    ⇒ `!= 0` 会**假绿**（实测：撤掉修复后本测试仍通过）。弱断言比没有断言更危险。
    """
    today = date.today()
    stale = today - timedelta(days=cf.MAX_LAG_DAYS + 5)
    _setup(tmp_path, monkeypatch, stale, today)
    rc = cf.main()
    assert rc == 1, "有告警却返回 %r ⇒ 每日链拿不到停更信号" % (rc,)
    assert "未更新" in open(cf.WARN, encoding="utf-8").read()


def test_exit_nonzero_when_features_missing(tmp_path, monkeypatch):
    """features.csv 不存在也算告警（原实现只打印，退出码仍是 0）。"""
    _setup(tmp_path, monkeypatch, date.today(), date.today())
    os.remove(cf.FEATURES)
    assert cf.main() == 1

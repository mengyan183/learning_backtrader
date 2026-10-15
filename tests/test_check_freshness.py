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
    # 既有 3 条测试只关心 features/prices 口径：把新增的产物列表清空，
    # 保证它们的行为**与改动前完全一致**（新口径由下面的新用例单独覆盖）。
    monkeypatch.setattr(cf, "EXTRA_FRESH", [])
    monkeypatch.setattr(cf, "REF_PRODUCTS", [])
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


# -------------------------------------------------- 覆盖不足修复（S-0）
# 背景：features.csv 停更会被抓到，但 pipeline 的另一个产物
# portfolio_features.csv 同样停更（实测 09-18）却**没有任何检查** ⇒ 护栏有盲区。
# 下面三例锁住：多余产物必须被查（fresh / 缺失都算 issue），
# 而参考快照类产物只报尾行日期、**不判 issue**（不改退出码）。


def _extra_fresh(tmp_path, monkeypatch, last):
    """把 EXTRA_FRESH 指到一个 tmp csv，尾行日期 = last。"""
    path = tmp_path / "portfolio_features.csv"
    _write(str(path), [last])
    monkeypatch.setattr(cf, "EXTRA_FRESH", [("组合特征", str(path))])


def test_extra_fresh_stale_is_issue(tmp_path, monkeypatch):
    """组合特征尾行滞后 > 阈值 ⇒ 返回非零，且告警里点名「组合特征」。"""
    today = date.today()
    _setup(tmp_path, monkeypatch, today, today)
    _extra_fresh(tmp_path, monkeypatch, today - timedelta(days=cf.MAX_LAG_DAYS + 5))
    rc = cf.main()
    assert rc == 1, "组合特征停更却返回 %r ⇒ 覆盖盲区未修复" % (rc,)
    assert "组合特征" in open(cf.WARN, encoding="utf-8").read()


def test_extra_fresh_missing_is_issue(tmp_path, monkeypatch):
    """组合特征不存在 ⇒ 返回非零，告警含「不存在」。"""
    today = date.today()
    _setup(tmp_path, monkeypatch, today, today)
    monkeypatch.setattr(cf, "EXTRA_FRESH",
                        [("组合特征", str(tmp_path / "nope.csv"))])
    rc = cf.main()
    assert rc == 1
    assert "不存在" in open(cf.WARN, encoding="utf-8").read()


def test_ref_products_missing_still_exit_zero(tmp_path, monkeypatch, capsys):
    """参考产物（快照/历史）缺失**不判 issue** ⇒ 退出码仍为 0，但 stdout 必须可见「缺失」。"""
    today = date.today()
    _setup(tmp_path, monkeypatch, today, today)
    monkeypatch.setattr(cf, "REF_PRODUCTS",
                        [("守猪待兔", str(tmp_path / "nope.csv"))])
    rc = cf.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "缺失" in out
    assert "守猪待兔" in out

# -*- coding: utf-8 -*-
"""R-3 守卫：`apply_variant` 是**纯函数**（与窗口无关）⇒ 每个变体只应算一次。

背景（WT-12 代码审查 R-3）：原实现把
`fv = vmod.apply_variant(feat, pf, vk)` 写在 `for (a, b) in windows:` **循环体内**
⇒ N 个季度窗就重算 N 次（结果完全相同）。逻辑正确，纯浪费。

**为什么用调用计数而不是断言源码文本**：源码文本断言"改代码即可改绿、无判别力"
（本仓已有此结论，见 `tests/data/test_shoutu_record.py` 的删除说明）。调用计数
是行为断言：把调用挪回循环内，本测试立刻失败。

不读真实 Data/：config 三个路径全部指到 tmp_path；runner / variants 全部 mock。
"""
import importlib.util
import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "evolve_walkforward.py")


def _load():
    spec = importlib.util.spec_from_file_location("evolve_walkforward", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wf = _load()


def test_apply_variant_called_once_per_variant_not_per_window(tmp_path, monkeypatch):
    idx = pd.date_range("2024-01-01", periods=400, freq="B")
    features = pd.DataFrame({"fg_index": 50.0, "target_position": 0.4}, index=idx)
    feat_csv = tmp_path / "features.csv"
    features.reset_index(names="date").to_csv(feat_csv, index=False)
    prices = pd.DataFrame({"date": idx, "symbol": "TQQQ", "open": 1.0, "high": 1.0,
                           "low": 1.0, "close": 1.0, "volume": 1.0})
    prices.to_csv(tmp_path / "prices.csv", index=False)

    monkeypatch.setattr(wf.config, "FEATURES_PATH", str(feat_csv))
    # ⚠️ `pf` **必须存在**：主流程是
    #     `fv = vmod.apply_variant(feat, pf, vk) if pf is not None else feat`
    #   pf=None 时整条变体路径被跳过 ⇒ apply_variant 一次都不调 ⇒ 本测试失去
    #   判别力（首版就踩了这个坑：实测 0 次调用而假绿）。
    pf_csv = tmp_path / "portfolio_features.csv"
    pd.DataFrame({"date": idx, "x": 1.0}).to_csv(pf_csv, index=False)
    monkeypatch.setattr(wf.config, "PORTFOLIO_FEATURES_PATH", str(pf_csv))
    monkeypatch.setattr(wf.config, "RAW_DIR", str(tmp_path))
    monkeypatch.setattr(wf.config, "SYMBOLS", ["TQQQ"])
    monkeypatch.setattr(wf.vmod, "VARIANT_KEYS", ["B0", "V-A", "V-B"])
    monkeypatch.setattr(sys, "argv", ["evolve_walkforward.py"])

    calls = []

    def fake_apply(feat, pf, vk):
        calls.append(vk)
        return feat

    monkeypatch.setattr(wf.vmod, "apply_variant", fake_apply)
    monkeypatch.setattr(wf.runner, "run_single",
                        lambda w, s: (None, pd.Series([0.001] * len(w))))
    monkeypatch.setattr(wf.runner, "performance_metrics",
                        lambda r: {"annual_return": 0.1, "max_drawdown": -0.1})

    windows = wf.quarter_windows(features)
    assert len(windows) >= 3, "样本不足则本测试无判别力：需要 >=3 个季度窗"

    wf.main()

    assert sorted(calls) == ["V-A", "V-B"], (
        "每个变体只应调用一次（%d 个窗 × 2 变体 = %d 次）；"
        "实际 %d 次 ⇒ apply_variant 又回到窗口循环里了"
        % (len(windows), len(windows) * 2, len(calls)))

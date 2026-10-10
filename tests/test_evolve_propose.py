# -*- coding: utf-8 -*-
"""WT-11 `scripts/evolve_propose.py` 测试（**不读真实 `Data/`**）。

覆盖：
- `--help` 可运行
- `write_proposal` 的**确定性判定**（adopt 判据 = OOS 年化更高 **且** 最大回撤不更深）
  与模板结构（六节齐全、文件名格式、`out_dir` 自动创建、basis 缺失回退）

不覆盖 `main()`：它要 patch ~10 处（config 路径 / runner / vmod / REPO / baseline.json），
收益低于成本；`write_proposal` 已是它唯一的文件写出口与全部判定逻辑所在。
"""
import importlib.util
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "evolve_propose.py")


def _load():
    spec = importlib.util.spec_from_file_location("evolve_propose", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ep = _load()

SPEC = {"label": "变体X", "basis": "先验依据（非调参）"}


def _m(ann, mdd, sharpe=1.0, calmar=1.0):
    """造一组 performance_metrics 形状的 dict（回撤按负数存）。"""
    return {"annual_return": ann, "max_drawdown": mdd,
            "sharpe": sharpe, "calmar": calmar}


# ------------------------------------------------------------------ --help
def test_help_runs():
    sys.argv = ["evolve_propose.py", "--help"]
    with pytest.raises(SystemExit) as exc:
        ep.main()
    assert exc.value.code == 0


# --------------------------------------------------------- write_proposal 判定
def test_adopt_when_annual_higher_and_drawdown_not_deeper(tmp_path):
    path, adopt = ep.write_proposal("TQQQ", "V1", SPEC,
                                    _m(0.10, -0.20), _m(0.12, -0.18), str(tmp_path))
    assert adopt is True
    text = open(path, encoding="utf-8").read()
    assert "提案候选（OOS 不劣化）" in text
    assert os.path.basename(path).startswith("proposal_TQQQ_V1_")


def test_reject_when_annual_lower(tmp_path):
    _, adopt = ep.write_proposal("TQQQ", "V1", SPEC,
                                 _m(0.10, -0.20), _m(0.09, -0.10), str(tmp_path))
    assert adopt is False


def test_reject_when_drawdown_deeper(tmp_path):
    """年化更高但回撤更深 ⇒ 不采纳（回撤是负数，`>=` 即"不更深"）。"""
    _, adopt = ep.write_proposal("TQQQ", "V1", SPEC,
                                 _m(0.10, -0.20), _m(0.12, -0.30), str(tmp_path))
    assert adopt is False


def test_drawdown_equal_is_adopt(tmp_path):
    """回撤**相等**算通过（`>=` 边界）。"""
    _, adopt = ep.write_proposal("TQQQ", "V1", SPEC,
                                 _m(0.10, -0.20), _m(0.12, -0.20), str(tmp_path))
    assert adopt is True


# --------------------------------------------------------- write_proposal 结构
def test_template_has_six_sections_and_verdict(tmp_path):
    path, _ = ep.write_proposal("TQQQ", "V1", SPEC,
                                _m(0.10, -0.20), _m(0.12, -0.18), str(tmp_path))
    text = open(path, encoding="utf-8").read()
    for sec in ("## 1. 依据", "## 2. 口径", "## 3. 回测证据",
                "## 4. 判定", "## 5. 风险", "## 6. 审批"):
        assert sec in text, "缺小节：%s" % sec
    assert "变体X" in text                       # spec["label"] 进模板
    assert "先验依据（非调参）" in text           # spec["basis"] 进模板
    assert ep.OOS_START in text                  # OOS 口径写进模板


def test_creates_missing_out_dir(tmp_path):
    out = tmp_path / "deep" / "nested"
    assert not out.exists()
    path, _ = ep.write_proposal("TQQQ", "V1", SPEC,
                                _m(0.1, -0.2), _m(0.1, -0.2), str(out))
    assert os.path.exists(path)


def test_missing_basis_falls_back_to_placeholder(tmp_path):
    path, _ = ep.write_proposal("TQQQ", "V1", {"label": "无依据"},
                                _m(0.1, -0.2), _m(0.1, -0.2), str(tmp_path))
    assert "待人工补充先验依据" in open(path, encoding="utf-8").read()

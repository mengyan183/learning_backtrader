# -*- coding: utf-8 -*-
"""MT-05 守卫：BH-FDR 用已知 p 值集合校验（规划 v2.0 A3b）。"""
import numpy as np
import pytest

from fg_system.fdr import bh_fdr


def test_known_answer_classic():
    """经典示例：p=[.01,.02,.03,.05,.20]，m=5，α=.05。

    阈值 t_k = k/5×.05 = [.01,.02,.03,.04,.05]：
      p_(4)=.05 > .04 ⇒ 最大 k=3 ⇒ 拒绝前 3 个（.01/.02/.03）。
    """
    p = np.array([0.01, 0.02, 0.03, 0.05, 0.20])
    rej = bh_fdr(p, alpha=0.05)
    assert list(rej) == [True, True, True, False, False]


def test_known_answer_single_above_threshold():
    """p=[.001,.20,.30]，m=3，α=.05：阈值 [.0167,.0333,.05] ⇒ 只拒绝 .001。"""
    p = np.array([0.001, 0.20, 0.30])
    rej = bh_fdr(p, alpha=0.05)
    assert list(rej) == [True, False, False]


def test_all_below_rejected():
    """全部 p 都低于各自阈值 ⇒ 全部拒绝。"""
    p = np.array([0.01, 0.01, 0.01])
    rej = bh_fdr(p, alpha=0.05)
    assert rej.all()


def test_none_rejected():
    """全部 p 都高于各自阈值 ⇒ 全部不拒绝。"""
    p = np.array([0.06, 0.10, 0.50])
    rej = bh_fdr(p, alpha=0.05)
    assert not rej.any()


def test_preserves_input_order():
    """返回顺序与输入一致（非排序后顺序）。"""
    p = np.array([0.20, 0.01, 0.30, 0.02])
    rej = bh_fdr(p, alpha=0.05)
    assert list(rej) == [False, True, False, True]


def test_nan_handled_as_missing():
    """NaN 不参与、不被拒绝。"""
    p = np.array([0.01, np.nan, 0.02])
    rej = bh_fdr(p, alpha=0.05)
    assert list(rej) == [True, False, True]


def test_empty():
    assert len(bh_fdr(np.array([]))) == 0

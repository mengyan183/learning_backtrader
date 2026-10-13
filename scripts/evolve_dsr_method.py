#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A3a Deflated Sharpe（规划 v2.0 A3a，v2.2 降级）—— 方法就绪 + 样例自证。

**只出两项**：
  ① 方法就绪：公式实现 + 已知答案样例自证（蒙特卡洛经验值 vs 理论值一致）；
  ② 显式声明："历史尝试不可枚举" ⇒ 现阶段 **不产结论**（N 需来自 A3c 台账
     `evolution/attempts-ledger.jsonl` 满 12 个月）。
产出**禁止**喂 `evolve_propose`。

公式（Bailey & López de Prado, 2014, "The Deflated Sharpe Ratio"）：
  - E[max SR_N] ≈ (1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e))，γ = Euler–Mascheroni ≈ 0.5772
  - 偏度/峰度修正：SR* = SR × (1 − skew·SR + ((kurt−1)/4)·SR²)
  - deflated SR 的 p 值 ≈ Φ( (SR* − E[max SR_N]) · √(T−1) / 1 )（单侧）
  - DSR = prob(deflated SR > 0) = 1 − p

用法：.venv/bin/python scripts/evolve_dsr_method.py
"""
import math
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0] + "/..")  # 仓库根

GAMMA = 0.5772156649015329  # Euler–Mascheroni 常数
PHI_INV = None


def _phi_inv(p):
    global PHI_INV
    if PHI_INV is None:
        from scipy.stats import norm
        PHI_INV = norm.ppf
    return PHI_INV(p)


def expected_max_sharpe(n, gamma=GAMMA):
    """N 次 iid 标准正态试验的期望最大 Sharpe（Bailey–LdP 近似）。

    注：这是论文口径的**近似公式**（用于 deflation 的 E[max SR_N]）；
    其与精确期望存在固有偏差（见 exact_expected_max），蒙特卡洛自证应
    对照精确值，而非本近似。
    """
    if n <= 1:
        return 0.0
    return ((1.0 - gamma) * _phi_inv(1.0 - 1.0 / n)
            + gamma * _phi_inv(1.0 - 1.0 / (n * math.e)))


def exact_expected_max(n):
    """精确 E[max]（已知答案）：E[max_N] = N·∫ x·φ(x)·Φ(x)^(N-1) dx。

    对标准正态，N=10 的精确值 ≈ 1.5388（已证）。用数值积分计算。
    """
    from scipy.integrate import quad
    from scipy.stats import norm
    if n <= 1:
        return 0.0
    f = lambda x: x * norm.pdf(x) * norm.cdf(x) ** (n - 1)
    val, _ = quad(f, -10.0, 10.0, limit=200)
    return n * val


def skew_adjusted_sharpe(sr, skewness, kurtosis):
    """偏度/峰度修正的 Sharpe（López de Prado 的 SR*）。"""
    return sr * (1.0 - skewness * sr + ((kurtosis - 1.0) / 4.0) * sr * sr)


def deflated_p_value(sr, n, skewness=0.0, kurtosis=3.0, t=252):
    """deflated SR 的 p 值（单侧，López de Prado 的 prob(DSR ≤ 0)）。"""
    from scipy.stats import norm
    sr_star = skew_adjusted_sharpe(sr, skewness, kurtosis)
    emax = expected_max_sharpe(n)
    z = (sr_star - emax) * math.sqrt(t - 1.0)
    return 1.0 - norm.cdf(z)


def _monte_carlo_self_test(n=10, n_groups=5000, seed=7):
    """自证：从 N(0,1) 生成 n_groups 组 × N 个 Sharpe 样本，取每组最大值，
    经验均值应 ≈ 理论 E[max SR_N]（容差 0.05）。"""
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n_groups, n))
    emp = float(x.max(axis=1).mean())
    theo = expected_max_sharpe(n)
    ok = abs(emp - theo) < 0.05
    return emp, theo, ok


def main():
    print("=== A3a Deflated Sharpe —— 方法就绪自证 ===")
    print("\n① 期望最大 Sharpe（Bailey & López de Prado 近似）：")
    for n in (1, 10, 50, 100):
        print("   N=%-4d E[max SR]=%.4f" % (n, expected_max_sharpe(n)))

    print("\n② 已知答案样例自证（蒙特卡洛，N=10，5000 组，种子 7）：")
    emp, theo, ok = _monte_carlo_self_test()
    exact = exact_expected_max(10)
    print("   经验 E[max SR]=%.4f" % emp)
    print("   精确 E[max SR]=%.4f（数值积分，已知答案）" % exact)
    print("   Bailey 近似    =%.4f（deflation 口径公式）" % theo)
    print("   经验 vs 精确 ⇒ %s" % ("一致 ✓" if abs(emp - exact) < 0.03 else "不一致 ✗"))
    if abs(emp - exact) >= 0.03:
        sys.exit(1)

    print("\n③ 偏度/峰度修正样例（López de Prado SR* 口径）：")
    sr_n = skew_adjusted_sharpe(0.5, 0.0, 3.0)
    print("   正态 sr=0.5, skew=0, kurt=3 ⇒ SR*=%.4f（kurt 项 =0.5·(2/4)·0.25=0.0625 非零）" % sr_n)

    print("\n④ Deflated p 值样例（N=1 ⇒ 无 deflation，p 由 T 决定）：")
    p1 = deflated_p_value(0.2, 1, t=252)
    print("   sr=0.2, N=1, T=252 ⇒ p=%.4f（单侧）" % p1)

    print("\n⑤ 显式声明：")
    print("   - 历史尝试**不可枚举**：台账（A3c, attempts-ledger.jsonl）只对")
    print("     未来生效 ⇒ 现阶段 A3a 拿不到历史 N ⇒ **不输出任何")
    print("     '校正后仍显著' 清单**（那需要 N）。")
    print("   - 本方法就绪产出**禁止**喂 evolve_propose（规划 v2.0 A3a 硬约束）。")
    print("\n✅ A3a 方法就绪（公式 + 自证一致 + 声明齐备）")


if __name__ == "__main__":
    main()

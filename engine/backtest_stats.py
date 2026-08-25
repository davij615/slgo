"""
stats.py — performance AND significance metrics (pure, offline-testable).

Beyond the usual CAGR/Sharpe/Sortino/drawdown, this implements the honesty layer
the validation research demanded:
  • PSR  — Probabilistic Sharpe Ratio (Bailey & Lopez de Prado): prob. the true
           Sharpe beats a benchmark, given sample length, skew, kurtosis.
  • MinTRL — Minimum Track Record Length: months/obs needed before a Sharpe is
             statistically distinguishable from the benchmark at a confidence.
  • Deflated Sharpe — PSR against the expected-max Sharpe from N trials, so a
             record that looks good only because many variants were tried is
             penalized. (You have tried many variants — this matters.)
"""
import math
from statistics import mean, pstdev


def to_returns(equity):
    return [equity[i] / equity[i - 1] - 1 for i in range(1, len(equity)) if equity[i - 1]]


def cagr(equity, ppy=252):
    if len(equity) < 2 or equity[0] <= 0:
        return None
    yrs = (len(equity) - 1) / ppy
    return (equity[-1] / equity[0]) ** (1 / yrs) - 1 if yrs > 0 else None


def ann_vol(rets, ppy=252):
    return pstdev(rets) * math.sqrt(ppy) if len(rets) > 1 else None


def sharpe(rets, rf=0.0, ppy=252):
    if len(rets) < 2:
        return None
    sd = pstdev(rets)
    return (mean(rets) - rf / ppy) / sd * math.sqrt(ppy) if sd else None


def sortino(rets, rf=0.0, ppy=252):
    if len(rets) < 2:
        return None
    rfp = rf / ppy
    dd = math.sqrt(mean([min(0, r - rfp) ** 2 for r in rets]))
    return (mean(rets) - rfp) / dd * math.sqrt(ppy) if dd else None


def max_drawdown(equity):
    peak, mdd = equity[0], 0.0
    for v in equity:
        peak = max(peak, v)
        if peak:
            mdd = min(mdd, v / peak - 1)
    return mdd


def calmar(equity, ppy=252):
    c, m = cagr(equity, ppy), max_drawdown(equity)
    return c / abs(m) if c is not None and m else None


def hit_rate(period_rets):
    v = [r for r in period_rets if r is not None]
    return sum(1 for r in v if r > 0) / len(v) if v else None


def _moments(rets):
    n = len(rets)
    m, sd = mean(rets), pstdev(rets)
    if sd == 0 or n < 2:
        return m, sd, 0.0, 3.0
    skew = sum((r - m) ** 3 for r in rets) / n / sd ** 3
    kurt = sum((r - m) ** 4 for r in rets) / n / sd ** 4
    return m, sd, skew, kurt


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_ppf(p):
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p <= phigh:
        q = p - 0.5; r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
           ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


def psr(rets, sr_benchmark=0.0):
    """Prob. true per-period Sharpe exceeds sr_benchmark (per period)."""
    n = len(rets)
    if n < 3:
        return None
    m, sd, skew, kurt = _moments(rets)
    if sd == 0:
        return None
    sr = m / sd
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr ** 2, 1e-9))
    return _norm_cdf((sr - sr_benchmark) * math.sqrt(n - 1) / denom)


def min_trl(rets, sr_benchmark=0.0, conf=0.95):
    """Min observations needed for the Sharpe to beat benchmark at `conf`."""
    m, sd, skew, kurt = _moments(rets)
    if sd == 0:
        return None
    sr = m / sd
    if sr <= sr_benchmark:
        return None
    z = _norm_ppf(conf)
    return 1 + (1 - skew * sr + (kurt - 1) / 4 * sr ** 2) * (z / (sr - sr_benchmark)) ** 2


def expected_max_sharpe(n_trials, sr_std):
    """Expected best per-period Sharpe from N independent trials (Bailey-LdP)."""
    if n_trials < 2:
        return 0.0
    g = 0.5772156649
    z1 = _norm_ppf(1 - 1.0 / n_trials)
    z2 = _norm_ppf(1 - 1.0 / (n_trials * math.e))
    return sr_std * ((1 - g) * z1 + g * z2)


def deflated_sharpe(rets, n_trials, sr_std=None):
    """PSR against the expected-max Sharpe from n_trials. sr_std = dispersion of
    per-period Sharpes across trials; defaults to the standard error of the Sharpe
    estimate (Lopez de Prado's recommended proxy), i.e. how much Sharpes scatter by
    chance across trials given this sample's length, skew and kurtosis."""
    n = len(rets)
    m, sd, skew, kurt = _moments(rets)
    if sd == 0 or n < 3:
        return None
    sr = m / sd
    if sr_std is None:
        sr_std = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr ** 2, 1e-9) / (n - 1))
    return psr(rets, sr_benchmark=expected_max_sharpe(n_trials, sr_std))


def summary(equity, period_rets=None, rf=0.0, ppy=252, n_trials=1):
    rets = to_returns(equity)
    out = {
        "cagr": cagr(equity, ppy), "ann_vol": ann_vol(rets, ppy),
        "sharpe": sharpe(rets, rf, ppy), "sortino": sortino(rets, rf, ppy),
        "max_drawdown": max_drawdown(equity), "calmar": calmar(equity, ppy),
        "psr_vs0": psr(rets, 0.0), "min_trl_obs": min_trl(rets, 0.0),
        "deflated_sharpe": deflated_sharpe(rets, n_trials) if n_trials > 1 else None,
        "n_trials": n_trials,
    }
    if period_rets is not None:
        out["hit_rate"] = hit_rate(period_rets)
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()}

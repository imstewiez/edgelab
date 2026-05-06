"""
CRITICAL VALIDATIONS - The Three Tests Before Any Capital Is Risked
1. Deflated Sharpe Ratio (selection bias correction)
2. True Hold-Out Test (train/test/validate on truly unseen periods)
3. Real H4 vs Resampled H4 Signal Verification
"""
import sys, os, warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from glob import glob
from scipy import stats
from scipy.special import erfc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtest.strategy import Strategy
from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig

XAU_CONFIG = ExecutionConfig(spread_pips=0.2, commission_per_lot=7.0, lot_size=100.0, trade_lots=1.0, slippage_pips=0.0, pip_value=1.0)

# ============================================================
# FROZEN MULTITF v1.0.0
# ============================================================
class MultiTF_v1(Strategy):
    def __init__(self):
        super().__init__("MultiTF_v1.0.0")
    def generate_signals(self, data):
        h1_mom = data["close"].pct_change(100)
        h4_close = data["close"].resample("4h").last().dropna()
        h4_mom = h4_close.pct_change(50)
        h4_mom_h1 = h4_mom.reindex(data.index, method="ffill")
        long = (h1_mom > 0) & (h4_mom_h1 > 0)
        short = (h1_mom < 0) & (h4_mom_h1 < 0)
        return pd.Series(np.where(long, 1, np.where(short, -1, 0)), index=data.index)

class MOM100(Strategy):
    def __init__(self):
        super().__init__("MOM100")
    def generate_signals(self, data):
        mom = data["close"].pct_change(100)
        return pd.Series(np.where(mom > 0, 1, np.where(mom < 0, -1, 0)), index=data.index)

class AdaptiveRegime(Strategy):
    def __init__(self):
        super().__init__("AdaptiveRegime")
    def generate_signals(self, data):
        d1_close = data["close"].resample("1D").last().dropna()
        d1_ret = d1_close.pct_change().dropna()
        vol = d1_ret.rolling(20).std() * np.sqrt(252)
        vol_h1 = vol.reindex(data.index, method="ffill")
        mom50 = data["close"].pct_change(50)
        mom100 = data["close"].pct_change(100)
        mom200 = data["close"].pct_change(200)
        sig = pd.Series(0, index=data.index)
        strong = vol_h1 > 0.20
        weak = vol_h1 < 0.10
        mod = ~(strong.fillna(False) | weak.fillna(False))
        sig[strong.fillna(False)] = np.where(mom50[strong.fillna(False)] > 0, 1, -1)
        sig[weak.fillna(False)] = np.where(mom200[weak.fillna(False)] > 0, 1, -1)
        sig[mod] = np.where(mom100[mod] > 0, 1, -1)
        return sig

# ============================================================
# DATA LOADING
# ============================================================
def load_all_data():
    base = os.path.join(os.path.dirname(__file__), "..", "..")
    
    # MT5 H1
    xau_h1 = pd.read_parquet(os.path.join(base, "data/raw/XAUUSD_H1.parquet"))
    if "time" in xau_h1.columns:
        xau_h1.set_index("time", inplace=True)
    
    # MT5 H4 (for verification)
    xau_h4 = None
    h4_path = os.path.join(base, "data/raw/XAUUSD_H4.parquet")
    if os.path.exists(h4_path):
        xau_h4 = pd.read_parquet(h4_path)
        if "time" in xau_h4.columns:
            xau_h4.set_index("time", inplace=True)
    
    # Dukascopy M1 -> H1
    dukas_paths = sorted(glob(os.path.join(base, "data/external/XAUUSD_M1_batch_*.parquet")))
    dfs = []
    for p in dukas_paths:
        d = pd.read_parquet(p)
        if "time" in d.columns:
            d.set_index("time", inplace=True)
        dfs.append(d)
    
    dukas = None
    if dfs:
        dukas = pd.concat(dfs).sort_index()
        dukas = dukas["close"].resample("1h").ohlc()
        dukas.columns = ["open", "high", "low", "close"]
    
    return xau_h1, xau_h4, dukas

def calc_metrics(equity):
    log_rets = np.log(equity / equity.shift(1)).dropna()
    ann_ret = log_rets.mean() * 252 * 24 * 100
    ann_vol = log_rets.std() * np.sqrt(252 * 24) * 100
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cummax = equity.cummax()
    dd = (equity - cummax) / cummax
    return {
        "sharpe": sharpe, "ann_ret": ann_ret, "ann_vol": ann_vol,
        "max_dd": dd.min() * 100, "total_ret": (equity.iloc[-1]/equity.iloc[0]-1)*100,
        "skew": log_rets.skew(), "kurt": log_rets.kurtosis(),
        "n_bars": len(log_rets)
    }

# ============================================================
# TEST 1: DEFLATED SHARPE RATIO
# ============================================================
def test_deflated_sharpe(data, strategies_tested=12):
    """
    Calculate Deflated Sharpe Ratio accounting for:
    1. Non-normality (skewness, kurtosis)
    2. Multiple testing / selection bias
    
    Based on Bailey & López de Prado (2014):
    'The Deflated Sharpe Ratio: Correcting for Selection Bias,
    Backtest Overfitting and Non-Normality'
    """
    print("=" * 80)
    print("TEST 1: DEFLATED SHARPE RATIO")
    print("=" * 80)
    print("Correcting for selection bias from testing %d strategies" % strategies_tested)
    print()
    
    bt = VectorizedBacktester(data, MultiTF_v1(), execution_config=XAU_CONFIG)
    bt.run()
    m = calc_metrics(bt.equity_curve)
    
    sr = m["sharpe"]
    T = m["n_bars"]
    skew = m["skew"]
    kurt = m["kurt"]
    
    # 1. Standard Sharpe
    print("Standard Sharpe Ratio:        %.4f" % sr)
    print("Number of observations:       %d" % T)
    print("Annualized return:            %.2f%%" % m["ann_ret"])
    print("Annualized volatility:        %.2f%%" % m["ann_vol"])
    print("Skewness:                     %.3f" % skew)
    print("Kurtosis:                     %.3f" % kurt)
    
    # 2. Sharpe p-value under normality
    # t-stat = SR * sqrt(T)
    t_stat = sr * np.sqrt(T)
    p_value = 1 - stats.norm.cdf(t_stat)
    print("\nUnder normality assumption:")
    print("  t-statistic:                %.3f" % t_stat)
    print("  p-value:                    %.6f" % p_value)
    
    # 3. Adjust for non-normality using Cornish-Fisher expansion
    # Adjusted t-stat accounts for skewness and kurtosis
    # Formula: t_adj = t * (1 + skew * t / 6 + (kurt - 3) * t^2 / 24)
    # But for the p-value, we adjust the critical value
    if abs(skew) > 0.1 or abs(kurt - 3) > 1:
        # Approximate adjusted Sharpe using Cornish-Fisher
        cf_adj = 1 - skew * sr / 6 + (kurt - 3) * sr**2 / 24
        sr_cf = sr * cf_adj
        t_cf = sr_cf * np.sqrt(T)
        p_cf = 1 - stats.norm.cdf(abs(t_cf))
        print("\nCornish-Fisher adjusted (non-normality):")
        print("  Adjusted Sharpe:            %.4f" % sr_cf)
        print("  Adjusted t-stat:            %.3f" % t_cf)
        print("  Adjusted p-value:           %.6f" % p_cf)
    else:
        sr_cf = sr
        p_cf = p_value
        print("\nReturns are approximately normal. No Cornish-Fisher adjustment needed.")
    
    # 4. Multiple testing adjustment (Bonferroni)
    # Probability of finding at least one strategy with this Sharpe by chance
    p_bonferroni = min(p_cf * strategies_tested, 1.0)
    print("\nMultiple testing adjustment (Bonferroni, N=%d):" % strategies_tested)
    print("  Family-wise p-value:        %.6f" % p_bonferroni)
    print("  Significant at 5%% level:    %s" % ("YES" if p_bonferroni < 0.05 else "NO"))
    print("  Significant at 1%% level:    %s" % ("YES" if p_bonferroni < 0.01 else "NO"))
    
    # 5. Deflated Sharpe (simplified)
    # Expected max Sharpe under null with N trials: E[max SR] ≈ sqrt(2 * ln(N) / T)
    expected_max_sr_null = np.sqrt(2 * np.log(strategies_tested) / T)
    print("\nExpected max Sharpe by chance (N=%d): %.4f" % (strategies_tested, expected_max_sr_null))
    
    # Deflated Sharpe = Observed SR - Expected max by chance
    sr_deflated = max(0, sr - expected_max_sr_null)
    print("Deflated Sharpe Ratio:        %.4f" % sr_deflated)
    
    # 6. Confidence interval
    # Var(SR) ≈ (1 + SR^2/2) / T  (for normal returns)
    var_sr = (1 + sr**2 / 2) / T
    se_sr = np.sqrt(var_sr)
    ci_lower = sr - 1.96 * se_sr
    ci_upper = sr + 1.96 * se_sr
    print("\n95%% Confidence Interval (standard): [%.3f, %.3f]" % (ci_lower, ci_upper))
    
    # 7. Haircut (percentage reduction due to selection bias)
    if sr > 0:
        haircut = (sr - sr_deflated) / sr * 100
        print("Sharpe 'haircut' from selection bias: %.1f%%" % haircut)
    
    print("\n" + "-" * 60)
    if sr_deflated > 0.5 and p_bonferroni < 0.05:
        print("VERDICT: Sharpe survives deflation. Edge likely real.")
    elif sr_deflated > 0.2:
        print("VERDICT: Marginal. Edge may exist but is weak.")
    else:
        print("VERDICT: Sharpe does NOT survive deflation. Likely data mining artifact.")
    print("-" * 60)
    
    return sr, sr_deflated, p_bonferroni

# ============================================================
# TEST 2: TRUE HOLD-OUT TEST
# ============================================================
def test_holdout(data):
    """
    Strict train/test/validate split:
    - Train: 2016-2022 (optimize - not that we have parameters)
    - Test: 2022-2024 (first unseen period)
    - Validate: 2024-2026 (truly held out)
    """
    print("\n" + "=" * 80)
    print("TEST 2: TRUE HOLD-OUT VALIDATION")
    print("=" * 80)
    print("Train: 2016-2022 | Test: 2022-2024 | Validate: 2024-2026")
    print()
    
    train = data[data.index < "2022-01-01"]
    test = data[(data.index >= "2022-01-01") & (data.index < "2024-01-01")]
    validate = data[data.index >= "2024-01-01"]
    
    periods = [
        ("TRAIN (2016-2022)", train),
        ("TEST (2022-2024)", test),
        ("VALIDATE (2024-2026)", validate),
    ]
    
    results = []
    for name, df in periods:
        if len(df) < 500:
            print("  %s: Insufficient data (%d bars)" % (name, len(df)))
            continue
        
        bt = VectorizedBacktester(df, MultiTF_v1(), execution_config=XAU_CONFIG)
        bt.run()
        m = calc_metrics(bt.equity_curve)
        results.append((name, m))
        
        print("  %-25s: Sharpe=%6.3f, AnnRet=%6.1f%%, Vol=%5.1f%%, DD=%6.1f%%, Bars=%d" % (
            name, m["sharpe"], m["ann_ret"], m["ann_vol"], m["max_dd"], m["n_bars"]))
    
    if len(results) >= 2:
        train_sharpe = results[0][1]["sharpe"]
        test_sharpe = results[1][1]["sharpe"] if len(results) > 1 else 0
        val_sharpe = results[2][1]["sharpe"] if len(results) > 2 else 0
        
        print("\n" + "-" * 60)
        print("Hold-Out Analysis:")
        print("  Train Sharpe:     %.3f" % train_sharpe)
        print("  Test Sharpe:      %.3f" % test_sharpe)
        print("  Validate Sharpe:  %.3f" % val_sharpe)
        
        decay = (train_sharpe - test_sharpe) / train_sharpe * 100 if train_sharpe > 0 else 0
        print("  Train->Test decay: %.1f%%" % decay)
        
        if test_sharpe > 0 and val_sharpe > 0:
            print("\n  VERDICT: Survives hold-out. Both test and validate are profitable.")
        elif test_sharpe > 0:
            print("\n  VERDICT: Marginal. Test profitable but validate insufficient data.")
        else:
            print("\n  VERDICT: FAILS hold-out. In-sample Sharpe does not generalize.")
        print("-" * 60)

# ============================================================
# TEST 3: REAL H4 vs RESAMPLED H4
# ============================================================
def test_h4_verification(h1_data, h4_data):
    """
    Compare MultiTF signals using:
    A. Real H4 bars from MT5
    B. H1 resampled to H4
    
    If signals match >95%, resampling is safe.
    If signals diverge significantly, our backtest is invalid.
    """
    print("\n" + "=" * 80)
    print("TEST 3: REAL H4 vs RESAMPLED H4 VERIFICATION")
    print("=" * 80)
    
    if h4_data is None or len(h4_data) == 0:
        print("Real H4 data not available. Cannot verify.")
        print("VERDICT: INCONCLUSIVE - Need to pull XAUUSD H4 from MT5")
        return
    
    print("Real H4 data: %d bars (%s to %s)" % (len(h4_data), h4_data.index[0], h4_data.index[-1]))
    print("H1 data: %d bars (%s to %s)" % (len(h1_data), h1_data.index[0], h1_data.index[-1]))
    
    # Generate signals using real H4
    # For real H4, we need to adapt MultiTF to use actual H4 data
    # Since H4 bars are at different timestamps, we'll compare on overlapping periods
    
    # Method: Use only H1 bars that align with H4 close times
    # H4 closes at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC
    # For each H4 bar, find the corresponding H1 bar at that exact time
    
    # Resampled signal (what we've been using)
    sig_resampled = MultiTF_v1().generate_signals(h1_data)
    
    # Real H4 signal
    # We need to compute H4 momentum from real H4 data, then apply to H1
    h4_mom = h4_data["close"].pct_change(50)
    h4_mom_h1 = h4_mom.reindex(h1_data.index, method="ffill")
    
    h1_mom = h1_data["close"].pct_change(100)
    
    sig_real = pd.Series(0, index=h1_data.index)
    long = (h1_mom > 0) & (h4_mom_h1 > 0)
    short = (h1_mom < 0) & (h4_mom_h1 < 0)
    sig_real[long] = 1
    sig_real[short] = -1
    
    # Compare on overlapping timestamps
    common_idx = sig_resampled.index.intersection(sig_real.index)
    sig_resampled_aligned = sig_resampled.reindex(common_idx)
    sig_real_aligned = sig_real.reindex(common_idx)
    
    agreement = (sig_resampled_aligned == sig_real_aligned).mean()
    disagreement = (sig_resampled_aligned != sig_real_aligned).sum()
    
    print("\nSignal Comparison:")
    print("  Common timestamps:          %d" % len(common_idx))
    print("  Agreement rate:             %.2f%%" % (agreement * 100))
    print("  Disagreeing bars:           %d" % disagreement)
    
    # Analyze disagreements
    if disagreement > 0:
        diff = sig_resampled_aligned - sig_real_aligned
        false_long = ((sig_resampled_aligned == 1) & (sig_real_aligned != 1)).sum()
        false_short = ((sig_resampled_aligned == -1) & (sig_real_aligned != -1)).sum()
        missed_long = ((sig_resampled_aligned != 1) & (sig_real_aligned == 1)).sum()
        missed_short = ((sig_resampled_aligned != -1) & (sig_real_aligned == -1)).sum()
        
        print("\nDisagreement breakdown:")
        print("  Resampled long, real not:   %d" % false_long)
        print("  Resampled short, real not:  %d" % false_short)
        print("  Real long, resampled not:   %d" % missed_long)
        print("  Real short, resampled not:  %d" % missed_short)
    
    print("\n" + "-" * 60)
    if agreement >= 0.95:
        print("VERDICT: EXCELLENT (>95%% agreement). Resampled H4 is safe.")
    elif agreement >= 0.90:
        print("VERDICT: ACCEPTABLE (90-95%%). Minor drift, monitor live.")
    elif agreement >= 0.80:
        print("VERDICT: CONCERNING (80-90%%). Significant drift. Need real H4.")
    else:
        print("VERDICT: UNACCEPTABLE (<80%%). Resampled H4 INVALIDATES backtest.")
    print("-" * 60)

# ============================================================
# BONUS: STRATEGY ROBUSTNESS (WALK-FORWARD WITH VARIANCE)
# ============================================================
def test_walkforward_variance(data):
    """Detailed walk-forward with per-window metrics."""
    print("\n" + "=" * 80)
    print("BONUS: WALK-FORWARD VARIANCE ANALYSIS")
    print("=" * 80)
    
    train = 3000
    step = 1000
    windows = []
    
    for start in range(0, len(data) - train - step, step):
        test = data.iloc[start + train:start + train + step]
        bt = VectorizedBacktester(test, MultiTF_v1(), execution_config=XAU_CONFIG)
        bt.run()
        m = calc_metrics(bt.equity_curve)
        windows.append(m)
    
    sharpes = [w["sharpe"] for w in windows]
    dds = [w["max_dd"] for w in windows]
    rets = [w["ann_ret"] for w in windows]
    
    print("Windows tested: %d" % len(windows))
    print("Sharpe mean:    %.3f" % np.mean(sharpes))
    print("Sharpe median:  %.3f" % np.median(sharpes))
    print("Sharpe std:     %.3f" % np.std(sharpes))
    print("Sharpe min:     %.3f" % min(sharpes))
    print("Sharpe max:     %.3f" % max(sharpes))
    print("Sharpe range:   %.3f" % (max(sharpes) - min(sharpes)))
    print("Positive:       %d/%d (%.1f%%)" % (sum(1 for s in sharpes if s > 0), len(sharpes),
          sum(1 for s in sharpes if s > 0) / len(sharpes) * 100))
    print("Sharpe > 1.0:   %d/%d (%.1f%%)" % (sum(1 for s in sharpes if s > 1.0), len(sharpes),
          sum(1 for s in sharpes if s > 1.0) / len(sharpes) * 100))
    
    # Check if any single window dominates
    window_returns = [(w["total_ret"] / 100 + 1) for w in windows]
    total_return = np.prod(window_returns) - 1
    
    # Which windows contributed most?
    contributions = [(w["total_ret"] / 100) for w in windows]
    best_window_idx = np.argmax(contributions)
    worst_window_idx = np.argmin(contributions)
    
    print("\nBest window:    #%d (Ret=%.1f%%)" % (best_window_idx + 1, contributions[best_window_idx] * 100))
    print("Worst window:   #%d (Ret=%.1f%%)" % (worst_window_idx + 1, contributions[worst_window_idx] * 100))
    
    # Check concentration: does top 20% of windows drive >50% of returns?
    sorted_contrib = sorted(contributions, reverse=True)
    top_20_pct = int(len(sorted_contrib) * 0.2) + 1
    top_20_contrib = sum(sorted_contrib[:top_20_pct])
    print("Top 20%% windows contribute: %.1f%% of total return" % (top_20_contrib / sum(contributions) * 100 if sum(contributions) != 0 else 0))

# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 80)
    print("CRITICAL VALIDATIONS - MultiTF v1.0.0")
    print("These tests determine if the strategy is real or a backtest fantasy.")
    print("=" * 80)
    
    h1, h4, dukas = load_all_data()
    
    # Build combined dataset
    if dukas is not None:
        combined = pd.concat([dukas, h1[h1.index >= "2021-01-01"]]).sort_index()
    else:
        combined = h1
    
    print("\nData summary:")
    print("  H1 bars:      %d (%s to %s)" % (len(h1), h1.index[0], h1.index[-1]))
    print("  H4 bars:      %s" % ("%d (%s to %s)" % (len(h4), h4.index[0], h4.index[-1]) if h4 is not None else "NOT AVAILABLE"))
    print("  Dukascopy:    %s" % ("%d (%s to %s)" % (len(dukas), dukas.index[0], dukas.index[-1]) if dukas is not None else "NOT AVAILABLE"))
    print("  Combined:     %d (%s to %s)" % (len(combined), combined.index[0], combined.index[-1]))
    
    # Run all tests
    sr, sr_deflated, p_val = test_deflated_sharpe(combined)
    test_holdout(combined)
    test_h4_verification(h1, h4)
    test_walkforward_variance(combined)
    
    # Final summary
    print("\n" + "=" * 80)
    print("OVERALL VALIDATION SUMMARY")
    print("=" * 80)
    
    print("\nTest 1 - Deflated Sharpe:")
    print("  Standard:   %.3f" % sr)
    print("  Deflated:   %.3f" % sr_deflated)
    print("  p-value:    %.6f" % p_val)
    
    print("\nTest 2 - Hold-Out:")
    print("  See per-period results above")
    
    print("\nTest 3 - H4 Verification:")
    print("  See signal agreement rate above")
    
    print("\n" + "-" * 60)
    print("FINAL ASSESSMENT:")
    
    if sr_deflated > 0.5 and p_val < 0.05:
        print("  Sharpe survives deflation: YES")
    else:
        print("  Sharpe survives deflation: NO / MARGINAL")
    
    if h4 is not None:
        # We printed the verdict in the function
        pass
    else:
        print("  H4 verification: INCONCLUSIVE (need real H4 data)")
    
    print("\nBefore risking $500:")
    print("  [ ] Deflated Sharpe > 0.5 and p < 0.05")
    print("  [ ] Hold-out test profitable on unseen data")
    print("  [ ] Real H4 vs resampled H4 agreement > 90%")
    print("  [ ] Walk-forward variance acceptable (std < 1.5)")
    print("  [ ] Paper trade for 2-4 weeks on demo")
    
    print("\nBefore risking $5,000:")
    print("  [ ] All above PLUS 3 months live track record")
    print("  [ ] Live Sharpe within 20% of backtest")
    print("  [ ] Max DD within backtest Monte Carlo 95th percentile")
    
    print("\nBefore client money:")
    print("  [ ] 12-24 months audited track record")
    print("  [ ] Regulatory compliance")
    print("  [ ] Independent third-party verification")
    print("-" * 60)

if __name__ == "__main__":
    main()

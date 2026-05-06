"""Phase 2.2: Cross-Asset Lead-Lag Analysis

Tests whether one asset's momentum predicts another's future returns.
Uses cross-correlation and Granger causality.

Assets tested: XAUUSD, EURUSD, NAS100 (all have 4+ years of data)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from scipy import stats
from itertools import permutations


def load_returns(symbol):
    base = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    h1 = pd.read_parquet(base / f"{symbol}_H1.parquet")
    if "time" in h1.columns:
        h1.set_index("time", inplace=True)
    returns = h1["close"].pct_change().dropna()
    return returns


def compute_momentum(returns, lookback=100):
    """Compute momentum as cumulative return over lookback bars."""
    return (1 + returns).rolling(lookback).apply(np.prod, raw=True) - 1


def cross_correlation(leader_rets, follower_rets, max_lag=24):
    """Compute cross-correlation at lags 0 to max_lag.
    
    Returns dict of {lag: correlation}.
    Positive lag = leader predicts follower (leader -> follower)
    """
    results = {}
    for lag in range(max_lag + 1):
        if lag == 0:
            corr = leader_rets.corr(follower_rets)
        else:
            corr = leader_rets.iloc[:-lag].corr(follower_rets.iloc[lag:])
        results[lag] = corr
    return results


def granger_test(leader, follower, max_lag=12):
    """Simplified Granger causality test.
    
    Tests whether past values of 'leader' improve prediction of 'follower'
    beyond just using past values of 'follower' alone.
    
    Returns F-statistic and p-value.
    """
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import r2_score
    
    # Align series
    df = pd.DataFrame({"follower": follower, "leader": leader}).dropna()
    if len(df) < max_lag * 3:
        return 0, 1.0
    
    # Model 1: follower ~ lagged follower only
    X1 = []
    y = []
    for i in range(max_lag, len(df)):
        X1.append([df["follower"].iloc[i - j] for j in range(1, max_lag + 1)])
        y.append(df["follower"].iloc[i])
    
    X1 = np.array(X1)
    y = np.array(y)
    
    m1 = LinearRegression().fit(X1, y)
    r2_1 = r2_score(y, m1.predict(X1))
    
    # Model 2: follower ~ lagged follower + lagged leader
    X2 = []
    for i in range(max_lag, len(df)):
        feats = [df["follower"].iloc[i - j] for j in range(1, max_lag + 1)]
        feats += [df["leader"].iloc[i - j] for j in range(1, max_lag + 1)]
        X2.append(feats)
    
    X2 = np.array(X2)
    m2 = LinearRegression().fit(X2, y)
    r2_2 = r2_score(y, m2.predict(X2))
    
    # F-test for nested models
    n = len(y)
    k1 = X1.shape[1]
    k2 = X2.shape[1]
    
    if r2_2 <= r2_1:
        return 0, 1.0
    
    f_stat = ((r2_2 - r2_1) / (k2 - k1)) / ((1 - r2_2) / (n - k2 - 1))
    
    # Approximate p-value (F-distribution with df1=k2-k1, df2=n-k2-1)
    p_value = 1 - stats.f.cdf(f_stat, k2 - k1, n - k2 - 1)
    
    return f_stat, p_value


def main():
    assets = ["XAUUSD", "EURUSD", "NAS100"]
    
    print("=" * 70)
    print("Phase 2.2: Cross-Asset Lead-Lag Analysis")
    print("=" * 70)
    
    # Load returns
    rets = {}
    for sym in assets:
        rets[sym] = load_returns(sym)
        print(f"Loaded {sym}: {len(rets[sym])} bars")
    
    # Compute momentum
    mom = {}
    for sym in assets:
        mom[sym] = compute_momentum(rets[sym], lookback=100)
    
    # Cross-correlation: momentum of A vs future returns of B
    print("\n" + "=" * 70)
    print("MOMENTUM -> FUTURE RETURNS (Cross-Correlation)")
    print("=" * 70)
    print(f"{'Leader':>10s} -> {'Follower':>10s} | {'Lag0':>7s} | {'Lag1':>7s} | {'Lag2':>7s} | {'Lag4':>7s} | {'Lag8':>7s} | {'Lag12':>7s} | {'Lag24':>7s}")
    print("-" * 85)
    
    cc_results = []
    for leader, follower in permutations(assets, 2):
        # Align
        common_idx = mom[leader].dropna().index.intersection(rets[follower].dropna().index)
        l = mom[leader].reindex(common_idx).dropna()
        f = rets[follower].reindex(common_idx).dropna()
        common_idx = l.index.intersection(f.index)
        l = l.reindex(common_idx)
        f = f.reindex(common_idx)
        
        cc = cross_correlation(l, f, max_lag=24)
        cc_results.append({
            "leader": leader,
            "follower": follower,
            **{f"lag_{k}": v for k, v in cc.items()},
        })
        
        print(f"{leader:>10s} -> {follower:>10s} | {cc[0]:>+7.4f} | {cc[1]:>+7.4f} | {cc[2]:>+7.4f} | {cc[4]:>+7.4f} | {cc[8]:>+7.4f} | {cc[12]:>+7.4f} | {cc[24]:>+7.4f}")
    
    # Find strongest lead-lag
    best = max(cc_results, key=lambda x: max(x[f"lag_{k}"] for k in range(1, 25) if f"lag_{k}" in x))
    best_lag = max(range(1, 25), key=lambda k: best[f"lag_{k}"])
    print(f"\nStrongest lead-lag: {best['leader']} -> {best['follower']} at lag {best_lag}h (corr={best[f'lag_{best_lag}']:+.4f})")
    
    # Granger causality
    print("\n" + "=" * 70)
    print("GRANGER CAUSALITY (Momentum -> Future Returns)")
    print("=" * 70)
    print(f"{'Leader':>10s} -> {'Follower':>10s} | {'F-stat':>8s} | {'p-value':>8s} | {'Result':>10s}")
    print("-" * 55)
    
    for leader, follower in permutations(assets, 2):
        common_idx = mom[leader].dropna().index.intersection(rets[follower].dropna().index)
        l = mom[leader].reindex(common_idx).dropna()
        f = rets[follower].reindex(common_idx).dropna()
        common_idx = l.index.intersection(f.index)
        l = l.reindex(common_idx)
        f = f.reindex(common_idx)
        
        if len(common_idx) < 1000:
            print(f"{leader:>10s} -> {follower:>10s} | {'N/A':>8s} | {'N/A':>8s} | {'insufficient':>10s}")
            continue
        
        f_stat, p_val = granger_test(l, f, max_lag=12)
        result = "CAUSAL" if p_val < 0.05 else "none"
        print(f"{leader:>10s} -> {follower:>10s} | {f_stat:>8.3f} | {p_val:>8.4f} | {result:>10s}")
    
    # Save
    out_dir = Path(__file__).parent.parent.parent.parent / "results" / "multi_asset"
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(cc_results).to_csv(out_dir / "lead_lag_crosscorr.csv", index=False)
    print(f"\nSaved: {out_dir / 'lead_lag_crosscorr.csv'}")


if __name__ == "__main__":
    main()

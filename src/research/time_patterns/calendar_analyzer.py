"""Phase 1.2: Weekday, Week-of-Month & Month Effects on MultiTF v1.0.0"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from collections import defaultdict
from scipy import stats

from multitf_platform.strategy.frozen.v1_0_0 import MultiTFStrategy, FrozenStrategyConfig
from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig


def load_data(symbol="XAUUSD"):
    base = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    h1 = pd.read_parquet(base / f"{symbol}_H1.parquet")
    if "time" in h1.columns:
        h1.set_index("time", inplace=True)
    h4 = pd.read_parquet(base / f"{symbol}_H4.parquet")
    if "time" in h4.columns:
        h4.set_index("time", inplace=True)
    return h1, h4


def run_backtest(h1, h4):
    strategy = MultiTFStrategy(FrozenStrategyConfig())
    signals = strategy.generate_signals_series(h1, h4)
    exec_cfg = ExecutionConfig(spread_pips=0.2, commission_per_lot=7.0,
                               lot_size=100.0, trade_lots=1.0,
                               slippage_pips=0.0, pip_value=1.0)
    class Mock:
        def __init__(self, sig): self.sig = sig
        def generate_signals(self, data): return self.sig.reindex(data.index).fillna(0)
    bt = VectorizedBacktester(h1, Mock(signals), execution_config=exec_cfg)
    bt.run()
    return bt.trades.copy()


def compute_stats(rets, label):
    if len(rets) < 5:
        return None
    wins = sum(1 for r in rets if r > 0)
    losses = len(rets) - wins
    win_rate = wins / len(rets) * 100
    avg_ret = np.mean(rets) * 100
    std_ret = np.std(rets) * 100
    sharpe = avg_ret / std_ret if std_ret > 0 else 0
    total = sum(rets) * 100
    # t-test vs zero
    t_stat, p_val = stats.ttest_1samp(rets, 0) if len(rets) >= 8 else (0, 1.0)
    return {
        "label": label,
        "trades": len(rets),
        "win_rate": win_rate,
        "avg_return_pct": avg_ret,
        "std_return_pct": std_ret,
        "sharpe": sharpe,
        "total_return_pct": total,
        "t_stat": t_stat,
        "p_value": p_val,
    }


def analyze_weekdays(trades):
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    buckets = {d: [] for d in days}
    for _, trade in trades.iterrows():
        ts = trade["entry_time"]
        if isinstance(ts, str): ts = pd.Timestamp(ts)
        day = days[ts.dayofweek]
        buckets[day].append(trade["return"])
    return [compute_stats(buckets[d], d) for d in days if len(buckets[d]) >= 5]


def analyze_week_of_month(trades):
    buckets = defaultdict(list)
    for _, trade in trades.iterrows():
        ts = trade["entry_time"]
        if isinstance(ts, str): ts = pd.Timestamp(ts)
        week = min((ts.day - 1) // 7 + 1, 4)
        buckets[f"W{week}"].append(trade["return"])
    return [compute_stats(buckets[k], k) for k in sorted(buckets) if len(buckets[k]) >= 5]


def analyze_month(trades):
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    buckets = {m: [] for m in months}
    for _, trade in trades.iterrows():
        ts = trade["entry_time"]
        if isinstance(ts, str): ts = pd.Timestamp(ts)
        buckets[months[ts.month - 1]].append(trade["return"])
    return [compute_stats(buckets[m], m) for m in months if len(buckets[m]) >= 5]


def analyze_nfp_week(trades):
    """NFP is first Friday of each month."""
    buckets = {"NFP_week": [], "other": []}
    for _, trade in trades.iterrows():
        ts = trade["entry_time"]
        if isinstance(ts, str): ts = pd.Timestamp(ts)
        # First Friday: dayofweek=4, day <= 7
        is_nfp_week = (ts.day <= 7)
        buckets["NFP_week" if is_nfp_week else "other"].append(trade["return"])
    return [compute_stats(buckets[k], k) for k in buckets if len(buckets[k]) >= 5]


def analyze_fomc_week(trades):
    """FOMC meetings are typically Wed of the 3rd week (check for Wed in week 3)."""
    buckets = {"FOMC_week": [], "other": []}
    for _, trade in trades.iterrows():
        ts = trade["entry_time"]
        if isinstance(ts, str): ts = pd.Timestamp(ts)
        # Rough proxy: 3rd week of month (days 15-21)
        is_fomc_week = (15 <= ts.day <= 21)
        buckets["FOMC_week" if is_fomc_week else "other"].append(trade["return"])
    return [compute_stats(buckets[k], k) for k in buckets if len(buckets[k]) >= 5]


def print_table(rows, title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")
    df = pd.DataFrame([r for r in rows if r is not None])
    if len(df) == 0:
        print("Insufficient data")
        return df
    df = df.sort_values("avg_return_pct", ascending=False)
    print(f"{'Label':>10s} | {'Trades':>6s} | {'Win%':>6s} | {'Avg%':>7s} | {'Sharpe':>6s} | {'Total%':>7s} | {'p-value':>8s}")
    print("-" * 70)
    for _, r in df.iterrows():
        sig = "***" if r["p_value"] < 0.01 else "**" if r["p_value"] < 0.05 else "*" if r["p_value"] < 0.10 else ""
        print(f"{r['label']:>10s} | {int(r['trades']):>6d} | {r['win_rate']:>6.1f} | {r['avg_return_pct']:>+7.3f} | {r['sharpe']:>6.2f} | {r['total_return_pct']:>+7.2f} | {r['p_value']:>8.4f} {sig}")
    print(f"\nSig: *** p<0.01, ** p<0.05, * p<0.10")
    return df


def main():
    print("=" * 70)
    print("Phase 1.2: Calendar Effects -- MultiTF v1.0.0")
    print("=" * 70)
    
    h1, h4 = load_data("XAUUSD")
    trades = run_backtest(h1, h4)
    print(f"Total trades: {len(trades)}")
    
    out_dir = Path(__file__).parent.parent.parent.parent / "results" / "time_patterns"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Weekday
    wd_df = print_table(analyze_weekdays(trades), "WEEKDAY EFFECTS")
    wd_df.to_csv(out_dir / "weekday_stats.csv", index=False) if len(wd_df) > 0 else None
    
    # Week of month
    wm_df = print_table(analyze_week_of_month(trades), "WEEK-OF-MONTH EFFECTS")
    wm_df.to_csv(out_dir / "weekofmonth_stats.csv", index=False) if len(wm_df) > 0 else None
    
    # Month
    m_df = print_table(analyze_month(trades), "MONTH EFFECTS")
    m_df.to_csv(out_dir / "month_stats.csv", index=False) if len(m_df) > 0 else None
    
    # NFP week
    nfp_df = print_table(analyze_nfp_week(trades), "NFP WEEK (FIRST FRIDAY) EFFECTS")
    nfp_df.to_csv(out_dir / "nfp_week_stats.csv", index=False) if len(nfp_df) > 0 else None
    
    # FOMC week
    fomc_df = print_table(analyze_fomc_week(trades), "FOMC WEEK (THIRD WEEK) EFFECTS")
    fomc_df.to_csv(out_dir / "fomc_week_stats.csv", index=False) if len(fomc_df) > 0 else None
    
    print(f"\nAll results saved to: {out_dir}")


if __name__ == "__main__":
    main()

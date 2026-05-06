"""Phase 1.1: Session & Hour Effects on MultiTF v1.0.0

Segments trades by trading session and hour-of-day to identify
when the momentum edge is strongest/weakest.

Sessions (UTC):
  Asian:     00:00 - 08:00
  London:    08:00 - 16:00
  NY:        13:00 - 21:00
  Overlap:   13:00 - 16:00 (London+NY)
  Off-Hours: 21:00 - 00:00
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from datetime import time
from collections import defaultdict

from multitf_platform.strategy.frozen.v1_0_0 import MultiTFStrategy, FrozenStrategyConfig
from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig


def get_session(dt: pd.Timestamp) -> str:
    """Return session name for a given timestamp (UTC)."""
    t = dt.time()
    if time(13, 0) <= t < time(16, 0):
        return "overlap"
    if time(0, 0) <= t < time(8, 0):
        return "asian"
    if time(8, 0) <= t < time(16, 0):
        return "london"
    if time(13, 0) <= t < time(21, 0):
        return "ny"
    return "off_hours"


def load_data(symbol="XAUUSD"):
    base = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    h1 = pd.read_parquet(base / f"{symbol}_H1.parquet")
    if "time" in h1.columns:
        h1.set_index("time", inplace=True)
    h4 = pd.read_parquet(base / f"{symbol}_H4.parquet")
    if "time" in h4.columns:
        h4.set_index("time", inplace=True)
    return h1, h4


def run_multitf_backtest(h1, h4):
    """Run MultiTF v1.0.0 vectorized backtest and return full trade log."""
    strategy = MultiTFStrategy(FrozenStrategyConfig())
    signals = strategy.generate_signals_series(h1, h4)
    
    exec_cfg = ExecutionConfig(
        spread_pips=0.2, commission_per_lot=7.0,
        lot_size=100.0, trade_lots=1.0,
        slippage_pips=0.0, pip_value=1.0,
    )
    
    class MockStrategy:
        def __init__(self, sig):
            self.sig = sig
        def generate_signals(self, data):
            return self.sig.reindex(data.index).fillna(0)
    
    bt = VectorizedBacktester(h1, MockStrategy(signals), execution_config=exec_cfg)
    bt.run()
    return bt.trades.copy(), bt.equity_curve


def analyze_by_session(trades):
    results = defaultdict(lambda: {"returns": [], "wins": 0, "losses": 0, "bars_held": []})
    for _, trade in trades.iterrows():
        entry_ts = trade["entry_time"]
        if isinstance(entry_ts, str):
            entry_ts = pd.Timestamp(entry_ts)
        session = get_session(entry_ts)
        ret = trade["return"]
        results[session]["returns"].append(ret)
        results[session]["bars_held"].append(trade.get("bars_held", 0))
        if ret > 0:
            results[session]["wins"] += 1
        else:
            results[session]["losses"] += 1
    return results


def analyze_by_hour(trades):
    results = defaultdict(lambda: {"returns": [], "wins": 0, "losses": 0, "bars_held": []})
    for _, trade in trades.iterrows():
        entry_ts = trade["entry_time"]
        if isinstance(entry_ts, str):
            entry_ts = pd.Timestamp(entry_ts)
        hour = entry_ts.hour
        ret = trade["return"]
        results[hour]["returns"].append(ret)
        results[hour]["bars_held"].append(trade.get("bars_held", 0))
        if ret > 0:
            results[hour]["wins"] += 1
        else:
            results[hour]["losses"] += 1
    return results


def compute_stats(results, name_col="session"):
    rows = []
    for key in sorted(results.keys()):
        data = results[key]
        rets = pd.Series(data["returns"])
        if len(rets) < 5:
            continue
        wins = data["wins"]
        losses = data["losses"]
        total = wins + losses
        win_rate = wins / total * 100 if total > 0 else 0
        avg_ret = rets.mean() * 100  # % per trade
        std_ret = rets.std() * 100
        trade_sharpe = avg_ret / std_ret if std_ret > 0 else 0
        avg_bars = np.mean(data["bars_held"]) if data["bars_held"] else 0
        total_ret = rets.sum() * 100
        # Expectancy = (win_rate * avg_win + loss_rate * avg_loss) / |avg_loss|
        wins_rets = rets[rets > 0]
        loss_rets = rets[rets <= 0]
        avg_win = wins_rets.mean() * 100 if len(wins_rets) > 0 else 0
        avg_loss = loss_rets.mean() * 100 if len(loss_rets) > 0 else 0
        expectancy = (win_rate/100 * avg_win + (1-win_rate/100) * avg_loss)
        rows.append({
            name_col: key,
            "trades": total,
            "win_rate": win_rate,
            "avg_return_pct": avg_ret,
            "std_return_pct": std_ret,
            "trade_sharpe": trade_sharpe,
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "expectancy_pct": expectancy,
            "avg_bars": avg_bars,
            "total_return_pct": total_ret,
        })
    return pd.DataFrame(rows)


def print_heatmap(df, col, title, fmt="+.3f"):
    print(f"\n{title}")
    print("-" * 65)
    vals = df[col].values
    vmin, vmax = vals.min(), vals.max()
    for _, row in df.iterrows():
        key = row["hour"] if "hour" in row else row["session"]
        val = row[col]
        if vmax > vmin:
            intensity = int(10 * (val - vmin) / (vmax - vmin))
        else:
            intensity = 5
        bar = "*" * intensity + "." * (10 - intensity)
        print(f"  {str(key):>10s} | {bar} {val:{fmt}}")


def main():
    print("=" * 70)
    print("Phase 1.1: Session & Hour Effects -- MultiTF v1.0.0")
    print("=" * 70)
    
    h1, h4 = load_data("XAUUSD")
    print(f"Loaded {len(h1)} H1 bars, {len(h4)} H4 bars")
    
    trades, equity = run_multitf_backtest(h1, h4)
    print(f"Total trades: {len(trades)}")
    
    out_dir = Path(__file__).parent.parent.parent.parent / "results" / "time_patterns"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Session analysis
    print("\n" + "=" * 70)
    print("SESSION ANALYSIS")
    print("=" * 70)
    
    session_results = analyze_by_session(trades)
    session_df = compute_stats(session_results, "session")
    session_df = session_df.sort_values("expectancy_pct", ascending=False)
    
    print(f"{'Session':>10s} | {'Trades':>6s} | {'Win%':>6s} | {'Avg%':>7s} | {'Sharpe':>7s} | {'Exp%':>7s} | {'AvgBars':>7s}")
    print("-" * 70)
    for _, r in session_df.iterrows():
        print(f"{r['session']:>10s} | {int(r['trades']):>6d} | {r['win_rate']:>6.1f} | {r['avg_return_pct']:>+7.3f} | {r['trade_sharpe']:>7.2f} | {r['expectancy_pct']:>+7.3f} | {r['avg_bars']:>7.1f}")
    
    session_df.to_csv(out_dir / "session_stats.csv", index=False)
    print(f"\nSaved: {out_dir / 'session_stats.csv'}")
    
    # Hour analysis
    print("\n" + "=" * 70)
    print("HOUR-OF-DAY ANALYSIS")
    print("=" * 70)
    
    hour_results = analyze_by_hour(trades)
    hour_df = compute_stats(hour_results, "hour")
    hour_df = hour_df.sort_values("hour")
    
    print(f"{'Hour':>5s} | {'Trades':>6s} | {'Win%':>6s} | {'Avg%':>7s} | {'Sharpe':>7s} | {'Exp%':>7s}")
    print("-" * 65)
    for _, r in hour_df.iterrows():
        print(f"{int(r['hour']):02d}:00 | {int(r['trades']):>6d} | {r['win_rate']:>6.1f} | {r['avg_return_pct']:>+7.3f} | {r['trade_sharpe']:>7.2f} | {r['expectancy_pct']:>+7.3f}")
    
    hour_df.to_csv(out_dir / "hour_stats.csv", index=False)
    print(f"\nSaved: {out_dir / 'hour_stats.csv'}")
    
    # Heatmaps
    print_heatmap(hour_df, "expectancy_pct", "Expectancy by Hour (% per trade)")
    print_heatmap(hour_df, "win_rate", "Win Rate by Hour (%)", fmt=".1f")
    
    # Key findings
    print(f"\n{'='*70}")
    print("KEY FINDINGS")
    print(f"{'='*70}")
    
    best_s = session_df.iloc[0]
    worst_s = session_df.iloc[-1]
    print(f"\nBest session:  {best_s['session']:10s} | Exp {best_s['expectancy_pct']:+.3f}% | WinRate {best_s['win_rate']:.1f}% | Trades {int(best_s['trades'])}")
    print(f"Worst session: {worst_s['session']:10s} | Exp {worst_s['expectancy_pct']:+.3f}% | WinRate {worst_s['win_rate']:.1f}% | Trades {int(worst_s['trades'])}")
    
    hour_by_exp = hour_df.sort_values("expectancy_pct", ascending=False)
    best_h = hour_by_exp.iloc[0]
    worst_h = hour_by_exp.iloc[-1]
    print(f"Best hour:     {int(best_h['hour']):02d}:00      | Exp {best_h['expectancy_pct']:+.3f}% | WinRate {best_h['win_rate']:.1f}% | Trades {int(best_h['trades'])}")
    print(f"Worst hour:    {int(worst_h['hour']):02d}:00      | Exp {worst_h['expectancy_pct']:+.3f}% | WinRate {worst_h['win_rate']:.1f}% | Trades {int(worst_h['trades'])}")
    
    # Recommendation
    print(f"\n{'='*70}")
    print("RECOMMENDATION")
    print(f"{'='*70}")
    top3_sessions = session_df.head(3)["session"].tolist()
    print(f"Strongest sessions (by expectancy): {', '.join(top3_sessions)}")
    
    # Hours with positive expectancy
    pos_hours = hour_df[hour_df["expectancy_pct"] > 0]
    if len(pos_hours) > 0:
        hours_list = [f"{int(h):02d}:00" for h in sorted(pos_hours["hour"].tolist())]
        print(f"Positive expectancy hours: {', '.join(hours_list)}")
    
    neg_hours = hour_df[hour_df["expectancy_pct"] < 0]
    if len(neg_hours) > 0:
        hours_list = [f"{int(h):02d}:00" for h in sorted(neg_hours["hour"].tolist())]
        print(f"Negative expectancy hours: {', '.join(hours_list)}")


if __name__ == "__main__":
    main()

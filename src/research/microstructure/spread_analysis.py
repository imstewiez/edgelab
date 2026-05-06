"""Phase 5: Market Microstructure -- Spread & Volume Analysis

Tests how spread and volume characteristics affect strategy performance.
Key questions:
- Does the strategy perform worse when spreads are wide?
- Is there a volume threshold below which signals are unreliable?
- Can we filter low-liquidity periods to improve Sharpe?

Uses actual spread data from MT5 (stored in parquet files).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np

from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig
from backtest.metrics import calculate_metrics
from multitf_platform.strategy.frozen.v1_0_0.signals import MultiTFStrategy
from multitf_platform.strategy.frozen.v1_0_0.config import FrozenStrategyConfig


def load_data(symbol="XAUUSD"):
    base = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    h1 = pd.read_parquet(base / f"{symbol}_H1.parquet")
    if "time" in h1.columns:
        h1.set_index("time", inplace=True)
    h4 = pd.read_parquet(base / f"{symbol}_H4.parquet")
    if "time" in h4.columns:
        h4.set_index("time", inplace=True)
    return h1, h4


def run_with_spread_filter(h1, h4, max_spread=None, min_volume=None):
    """Run backtest filtering out bars with wide spread or low volume."""
    cfg = FrozenStrategyConfig()
    strat = MultiTFStrategy(cfg)
    signals = strat.generate_signals_series(h1, h4)
    
    # Apply filters
    blocked = pd.Series(False, index=h1.index)
    
    if max_spread is not None and "spread" in h1.columns:
        # spread in MT5 points for XAUUSD (1 point = $0.01)
        # Typical spread: 20-50 points = $0.20-$0.50
        blocked |= h1["spread"] > max_spread
    
    if min_volume is not None and "tick_volume" in h1.columns:
        blocked |= h1["tick_volume"] < min_volume
    
    signals[blocked] = 0
    
    class MockStrat:
        def __init__(self, sig): self.sig = sig
        def generate_signals(self, data): return self.sig.reindex(data.index).fillna(0)
    
    exec_cfg = ExecutionConfig(
        spread_pips=0.2, commission_per_lot=7.0,
        lot_size=100.0, trade_lots=0.01,
        slippage_pips=0.5, pip_value=1.0,
    )
    
    bt = VectorizedBacktester(h1, MockStrat(signals), execution_config=exec_cfg)
    bt.run()
    return bt


def analyze_spread_distribution(h1):
    """Print spread statistics."""
    if "spread" not in h1.columns:
        print("No spread data available")
        return None
    
    s = h1["spread"].dropna()
    print(f"Spread distribution (points):")
    print(f"  Mean:   {s.mean():.1f}")
    print(f"  Median: {s.median():.1f}")
    print(f"  Std:    {s.std():.1f}")
    print(f"  P10:    {s.quantile(0.10):.1f}")
    print(f"  P25:    {s.quantile(0.25):.1f}")
    print(f"  P75:    {s.quantile(0.75):.1f}")
    print(f"  P90:    {s.quantile(0.90):.1f}")
    print(f"  P95:    {s.quantile(0.95):.1f}")
    print(f"  P99:    {s.quantile(0.99):.1f}")
    print(f"  Max:    {s.max():.1f}")
    return s


def main():
    print("=" * 70)
    print("Phase 5: Market Microstructure -- Spread & Volume Analysis")
    print("=" * 70)
    
    h1, h4 = load_data("XAUUSD")
    print(f"Loaded H1: {len(h1)} bars, H4: {len(h4)} bars")
    
    # Analyze spread distribution
    print()
    s = analyze_spread_distribution(h1)
    
    if s is None:
        print("Cannot proceed without spread data")
        return
    
    # Test spread filters
    print("\n" + "=" * 70)
    print("SPREAD FILTER TESTS")
    print("=" * 70)
    
    spread_thresholds = [None, 100, 75, 50, 40, 30, 25]
    results = []
    
    for thresh in spread_thresholds:
        bt = run_with_spread_filter(h1, h4, max_spread=thresh, min_volume=None)
        periods = 252 * 24
        m = calculate_metrics(bt.equity_curve, trades=bt.trades, periods_per_year=periods)
        
        desc = f"Max spread: {thresh}" if thresh else "No filter"
        blocked_pct = (h1["spread"] > thresh).mean() * 100 if thresh else 0
        
        res = {
            "filter": desc,
            "sharpe": m.get("sharpe_ratio", 0),
            "ann_return": m.get("ann_return_pct", 0),
            "max_dd": m.get("max_drawdown_pct", 0),
            "trades": m.get("num_trades", 0),
            "win_rate": m.get("win_rate_pct", 0),
            "blocked_pct": blocked_pct,
        }
        results.append(res)
        print(f"  {desc:20s} | Sharpe {res['sharpe']:>+7.3f} | Return {res['ann_return']:>+7.1f}% | DD {res['max_dd']:>7.1f}% | Trades {res['trades']:>4d} | Blocked {res['blocked_pct']:>5.1f}%")
    
    # Volume filters
    if "tick_volume" in h1.columns:
        print("\n" + "=" * 70)
        print("VOLUME FILTER TESTS")
        print("=" * 70)
        
        v = h1["tick_volume"].dropna()
        print(f"Volume distribution:")
        print(f"  Mean:   {v.mean():.0f}")
        print(f"  Median: {v.median():.0f}")
        print(f"  P10:    {v.quantile(0.10):.0f}")
        print(f"  P25:    {v.quantile(0.25):.0f}")
        
        vol_thresholds = [None, int(v.quantile(0.10)), int(v.quantile(0.25)), int(v.quantile(0.50))]
        for thresh in vol_thresholds:
            bt = run_with_spread_filter(h1, h4, max_spread=None, min_volume=thresh)
            periods = 252 * 24
            m = calculate_metrics(bt.equity_curve, trades=bt.trades, periods_per_year=periods)
            
            desc = f"Min volume: {thresh}" if thresh else "No filter"
            blocked_pct = (h1["tick_volume"] < thresh).mean() * 100 if thresh else 0
            
            res = {
                "filter": desc,
                "sharpe": m.get("sharpe_ratio", 0),
                "ann_return": m.get("ann_return_pct", 0),
                "max_dd": m.get("max_drawdown_pct", 0),
                "trades": m.get("num_trades", 0),
                "win_rate": m.get("win_rate_pct", 0),
                "blocked_pct": blocked_pct,
            }
            results.append(res)
            print(f"  {desc:20s} | Sharpe {res['sharpe']:>+7.3f} | Return {res['ann_return']:>+7.1f}% | DD {res['max_dd']:>7.1f}% | Trades {res['trades']:>4d} | Blocked {res['blocked_pct']:>5.1f}%")
    
    # Save
    df = pd.DataFrame(results)
    out = Path(__file__).parent.parent.parent.parent / "results" / "microstructure"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "spread_volume_analysis.csv", index=False)
    
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    baseline = df[df["filter"] == "No filter"].iloc[0]
    print(f"Baseline: Sharpe {baseline['sharpe']:.3f}, Return {baseline['ann_return']:.1f}%, Trades {baseline['trades']}")
    
    best = df.loc[df["sharpe"].idxmax()]
    print(f"Best filter: {best['filter']} | Sharpe {best['sharpe']:.3f} ({best['sharpe'] - baseline['sharpe']:+.3f})")
    
    print(f"\nSaved: {out / 'spread_volume_analysis.csv'}")


if __name__ == "__main__":
    main()

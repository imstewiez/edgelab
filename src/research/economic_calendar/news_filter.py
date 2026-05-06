"""Phase 4: Economic Calendar & News Event Filtering

Tests whether avoiding high-impact news days improves performance.
Based on Phase 1.2 findings:
- NFP week (Week 1): significantly worse (p=0.0008)
- FOMC week: marginally worse
- Specific days around NFP/FOMC may be particularly toxic

This module:
1. Builds a synthetic economic calendar for 2021-2026
2. Tests MultiTF performance with/without news filters
3. Recommends calendar-based risk rules for live trading
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Optional

from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig
from backtest.metrics import calculate_metrics
from multitf_platform.strategy.frozen.v1_0_0.signals import MultiTFStrategy
from multitf_platform.strategy.frozen.v1_0_0.config import FrozenStrategyConfig


@dataclass
class NewsEvent:
    date: pd.Timestamp
    event_type: str  # "NFP", "FOMC", "CPI", "GDP", "ECB", "BOE", "BOJ"
    impact: str  # "high", "medium", "low"
    time_utc: Optional[str] = None


def build_synthetic_calendar(start="2021-12-01", end="2026-05-01") -> List[NewsEvent]:
    """Build approximate calendar of major events.
    
    Uses known schedules:
    - NFP: First Friday of each month, 8:30 AM EST (13:30 UTC)
    - FOMC: 8 meetings/year, typically Wed of second or third week
    - CPI: Second week of month, typically Tue or Wed
    """
    events = []
    dr = pd.date_range(start, end, freq="D")
    
    for date in dr:
        # NFP: First Friday
        if date.dayofweek == 4 and date.day <= 7:
            events.append(NewsEvent(date, "NFP", "high", "13:30"))
        
        # FOMC: Approximate 8 meetings/year
        # Jan, Mar, May, Jun, Jul, Sep, Nov, Dec -- typically mid-month Wed
        if date.dayofweek == 2 and 15 <= date.day <= 23:
            if date.month in [1, 3, 5, 6, 7, 9, 11, 12]:
                events.append(NewsEvent(date, "FOMC", "high", "19:00"))
        
        # CPI: ~13th of month
        if date.day == 13:
            events.append(NewsEvent(date, "CPI", "high", "13:30"))
        
        # ECB: ~second Thu of month (approximate)
        if date.dayofweek == 3 and 8 <= date.day <= 14:
            if date.month in [1, 3, 4, 6, 7, 9, 10, 12]:
                events.append(NewsEvent(date, "ECB", "medium", "13:15"))
    
    return events


def apply_news_filter(trades_df: pd.DataFrame, events: List[NewsEvent], 
                      buffer_hours: int = 24) -> pd.DataFrame:
    """Mark trades that occurred within buffer_hours of a high-impact event.
    
    Returns trades_df with 'near_event' column.
    """
    trades = trades_df.copy()
    trades["near_event"] = False
    
    high_impact = [e for e in events if e.impact == "high"]
    
    for e in high_impact:
        event_time = pd.Timestamp(e.date)
        mask = (trades.index >= event_time - timedelta(hours=buffer_hours)) & \
               (trades.index <= event_time + timedelta(hours=buffer_hours))
        trades.loc[mask, "near_event"] = True
    
    return trades


def run_with_filter(h1, h4, events, filter_type="none", buffer_hours=24):
    """Run backtest with news filter.
    
    filter_type: "none", "nfp_only", "fomc_only", "all_high", "nfp_week", "fomc_week"
    """
    cfg = FrozenStrategyConfig()
    strat = MultiTFStrategy(cfg)
    
    exec_cfg = ExecutionConfig(
        spread_pips=0.2, commission_per_lot=7.0,
        lot_size=100.0, trade_lots=0.01,
        slippage_pips=0.5, pip_value=1.0,
    )
    
    # Standard backtest
    signals = strat.generate_signals_series(h1, h4)
    class MockStrat:
        def __init__(self, sig): self.sig = sig
        def generate_signals(self, data): return self.sig.reindex(data.index).fillna(0)
    bt = VectorizedBacktester(h1, MockStrat(signals), execution_config=exec_cfg)
    bt.run()
    
    if filter_type == "none":
        return bt
    
    # Rebuild with filter
    # Get trade timestamps
    trades = bt.trades.copy()
    if len(trades) == 0:
        return bt
    
    # Determine blocked periods
    blocked = pd.Series(False, index=h1.index)
    
    # Make h1 index timezone-naive for comparison
    h1_idx = h1.index.tz_localize(None) if h1.index.tz else h1.index
    
    if filter_type == "nfp_only":
        for e in events:
            if e.event_type == "NFP":
                t = pd.Timestamp(e.date)
                mask = (h1_idx >= t - timedelta(hours=buffer_hours)) & \
                       (h1_idx <= t + timedelta(hours=buffer_hours))
                blocked |= mask
    elif filter_type == "fomc_only":
        for e in events:
            if e.event_type == "FOMC":
                t = pd.Timestamp(e.date)
                mask = (h1_idx >= t - timedelta(hours=buffer_hours)) & \
                       (h1_idx <= t + timedelta(hours=buffer_hours))
                blocked |= mask
    elif filter_type == "all_high":
        for e in events:
            if e.impact == "high":
                t = pd.Timestamp(e.date)
                mask = (h1_idx >= t - timedelta(hours=buffer_hours)) & \
                       (h1_idx <= t + timedelta(hours=buffer_hours))
                blocked |= mask
    elif filter_type == "nfp_week":
        for e in events:
            if e.event_type == "NFP":
                week_start = pd.Timestamp(e.date) - timedelta(days=e.date.dayofweek)
                week_end = week_start + timedelta(days=6)
                mask = (h1_idx >= week_start) & (h1_idx <= week_end)
                blocked |= mask
    elif filter_type == "fomc_week":
        for e in events:
            if e.event_type == "FOMC":
                week_start = pd.Timestamp(e.date) - timedelta(days=e.date.dayofweek)
                week_end = week_start + timedelta(days=6)
                mask = (h1_idx >= week_start) & (h1_idx <= week_end)
                blocked |= mask
    
    # Filter signals
    signals[blocked] = 0  # Block during news
    
    class FilteredStrat:
        def __init__(self, sig):
            self.sig = sig
        def generate_signals(self, data):
            return self.sig.reindex(data.index).fillna(0)
    
    bt2 = VectorizedBacktester(h1, FilteredStrat(signals), execution_config=exec_cfg)
    bt2.run()
    return bt2


def main():
    print("=" * 70)
    print("Phase 4: Economic Calendar & News Event Filtering")
    print("=" * 70)
    
    # Load data
    base = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    h1 = pd.read_parquet(base / "XAUUSD_H1.parquet")
    if "time" in h1.columns:
        h1.set_index("time", inplace=True)
    h4 = pd.read_parquet(base / "XAUUSD_H4.parquet")
    if "time" in h4.columns:
        h4.set_index("time", inplace=True)
    
    print(f"Loaded H1: {len(h1)} bars, H4: {len(h4)} bars")
    
    # Build calendar
    events = build_synthetic_calendar()
    high = [e for e in events if e.impact == "high"]
    print(f"Synthetic calendar: {len(events)} events, {len(high)} high-impact")
    
    # Run scenarios
    scenarios = {
        "none": "No filter (baseline)",
        "nfp_only": "Avoid NFP day +/- 24h",
        "fomc_only": "Avoid FOMC day +/- 24h",
        "all_high": "Avoid all high-impact +/- 24h",
        "nfp_week": "Avoid entire NFP week",
        "fomc_week": "Avoid entire FOMC week",
    }
    
    results = []
    for key, desc in scenarios.items():
        print(f"\n--- {desc} ---")
        bt = run_with_filter(h1, h4, events, filter_type=key, buffer_hours=24)
        
        periods = 252 * 24
        m = calculate_metrics(bt.equity_curve, trades=bt.trades, periods_per_year=periods)
        
        res = {
            "scenario": key,
            "description": desc,
            "sharpe": m.get("sharpe_ratio", 0),
            "ann_return": m.get("ann_return_pct", 0),
            "max_dd": m.get("max_drawdown_pct", 0),
            "trades": m.get("num_trades", 0),
            "win_rate": m.get("win_rate_pct", 0),
        }
        results.append(res)
        print(f"  Sharpe {res['sharpe']:>+7.3f} | Return {res['ann_return']:>+7.1f}% | DD {res['max_dd']:>7.1f}% | Trades {res['trades']:>4d}")
    
    # Save
    df = pd.DataFrame(results)
    out = Path(__file__).parent.parent.parent.parent / "results" / "economic_calendar"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "news_filter_results.csv", index=False)
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    baseline = df[df["scenario"] == "none"].iloc[0]
    print(f"Baseline: Sharpe {baseline['sharpe']:.3f}, Return {baseline['ann_return']:.1f}%, DD {baseline['max_dd']:.1f}%, Trades {baseline['trades']}")
    print()
    for _, r in df.iterrows():
        if r["scenario"] == "none":
            continue
        delta_sharpe = r["sharpe"] - baseline["sharpe"]
        delta_trades = r["trades"] - baseline["trades"]
        print(f"{r['description']:40s} | Sharpe {r['sharpe']:>+7.3f} ({delta_sharpe:>+6.3f}) | Trades {r['trades']:>4d} ({delta_trades:>+4d})")
    
    best = df[df["scenario"] != "none"].loc[df["sharpe"].idxmax()]
    print(f"\nBest filter: {best['description']} | Sharpe {best['sharpe']:.3f}")
    
    print(f"\nSaved: {out / 'news_filter_results.csv'}")


if __name__ == "__main__":
    main()

"""Phase 3: Scalping Feasibility on XAUUSD M15

Tests whether fast momentum strategies (M15/M5) survive realistic
transaction costs on a $300 retail account.

Key question: Is scalping viable with 0.01 lots, $7/lot commission,
and real spreads from MT5 data?
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np

from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig
from backtest.metrics import calculate_metrics


def load_m15(symbol="XAUUSD"):
    base = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    h1 = pd.read_parquet(base / f"{symbol}_H1.parquet")
    if "time" in h1.columns:
        h1.set_index("time", inplace=True)
    # Resample H1 to M15 (for backtest only -- costs still apply)
    m15 = h1.resample("15min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "spread": "mean", "tick_volume": "sum",
    }).dropna()
    return m15


def strategy_mom(m15, lookback=20):
    """Simple momentum on M15."""
    mom = m15["close"] / m15["close"].shift(lookback) - 1
    return pd.Series(np.where(mom > 0, 1, np.where(mom < 0, -1, 0)), index=m15.index)


def strategy_mom_fast_slow(m15, fast=10, slow=40):
    """Fast momentum + slow confirmation."""
    m_fast = m15["close"] / m15["close"].shift(fast) - 1
    m_slow = m15["close"] / m15["close"].shift(slow) - 1
    return pd.Series(np.where(
        (m_fast > 0) & (m_slow > 0), 1,
        np.where((m_fast < 0) & (m_slow < 0), -1, 0)
    ), index=m15.index)


def strategy_session_open(m15, session_hour=13):
    """Trade direction of first 2 M15 bars after session open."""
    signals = pd.Series(0, index=m15.index)
    for i in range(1, len(m15)):
        curr = m15.index[i]
        prev = m15.index[i - 1]
        # Check if this bar starts at session open hour
        if curr.hour == session_hour and prev.hour != session_hour:
            if i + 1 < len(m15):
                dir_ = 1 if m15["close"].iloc[i] > m15["open"].iloc[i] else -1
                signals.iloc[i] = dir_
                signals.iloc[i + 1] = dir_
    return signals


def run_backtest(m15, signals, exec_cfg, name):
    class Mock:
        def __init__(self, sig): self.sig = sig
        def generate_signals(self, data): return self.sig.reindex(data.index).fillna(0)
    
    bt = VectorizedBacktester(m15, Mock(signals), execution_config=exec_cfg)
    bt.run()
    
    periods = 252 * 24 * 4  # M15: 4 bars per hour
    m = calculate_metrics(bt.equity_curve, trades=bt.trades, periods_per_year=periods)
    
    return {
        "name": name,
        "sharpe": m.get("sharpe_ratio", 0),
        "ann_return": m.get("ann_return_pct", 0),
        "max_dd": m.get("max_drawdown_pct", 0),
        "trades": m.get("num_trades", 0),
        "win_rate": m.get("win_rate_pct", 0),
        "profit_factor": m.get("profit_factor", 0),
        "avg_trade": m.get("avg_trade_return_pct", 0),
    }


def main():
    print("=" * 70)
    print("Phase 3: Scalping Feasibility -- XAUUSD M15")
    print("=" * 70)
    
    m15 = load_m15("XAUUSD")
    print(f"Loaded {len(m15)} M15 bars ({len(m15)/4/24:.0f} days)")
    
    # Cost scenarios
    scenarios = {
        "tight_ecn": ExecutionConfig(
            spread_pips=0.5, commission_per_lot=3.5,
            lot_size=100.0, trade_lots=0.01,
            slippage_pips=0.2, pip_value=1.0,
        ),
        "typical": ExecutionConfig(
            spread_pips=2.0, commission_per_lot=7.0,
            lot_size=100.0, trade_lots=0.01,
            slippage_pips=0.5, pip_value=1.0,
        ),
        "wide_retail": ExecutionConfig(
            spread_pips=5.0, commission_per_lot=10.0,
            lot_size=100.0, trade_lots=0.01,
            slippage_pips=1.0, pip_value=1.0,
        ),
    }
    
    strategies = {
        "MOM20": strategy_mom(m15, 20),
        "MOM10": strategy_mom(m15, 10),
        "MOM10+40": strategy_mom_fast_slow(m15, 10, 40),
        "SessionOpen_13UTC": strategy_session_open(m15, 13),
    }
    
    results = []
    for strat_name, signals in strategies.items():
        print(f"\n--- {strat_name} ---")
        for cost_name, exec_cfg in scenarios.items():
            res = run_backtest(m15, signals, exec_cfg, f"{strat_name}_{cost_name}")
            res["strategy"] = strat_name
            res["costs"] = cost_name
            results.append(res)
            status = "VIABLE" if res["sharpe"] > 0.5 else "MARGINAL" if res["sharpe"] > 0 else "DEAD"
            print(f"  {cost_name:15s} | Sharpe {res['sharpe']:>+7.3f} | Return {res['ann_return']:>+7.1f}% | DD {res['max_dd']:>7.1f}% | Trades {res['trades']:>4d} | {status}")
    
    # Summary table
    df = pd.DataFrame(results)
    out = Path(__file__).parent.parent.parent.parent / "results" / "scalping"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "scalping_feasibility.csv", index=False)
    
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"{'Strategy':>20s} | {'Costs':>15s} | {'Sharpe':>7s} | {'Return':>8s} | {'DD':>8s} | {'Trades':>6s} | {'Status':>10s}")
    print("-" * 70)
    for _, r in df.iterrows():
        status = "VIABLE" if r["sharpe"] > 0.5 else "MARGINAL" if r["sharpe"] > 0 else "DEAD"
        print(f"{r['strategy']:>20s} | {r['costs']:>15s} | {r['sharpe']:>+7.3f} | {r['ann_return']:>+8.1f} | {r['max_dd']:>+8.1f} | {r['trades']:>6d} | {status:>10s}")
    
    viable = df[df["sharpe"] > 0.5]
    print(f"\nViable scalping strategies: {len(viable)}")
    if len(viable) > 0:
        for _, r in viable.iterrows():
            print(f"  {r['strategy']} @ {r['costs']} | Sharpe {r['sharpe']:.3f}")
    else:
        print("  NONE -- Scalping is not viable with realistic retail costs.")
    
    print(f"\nSaved: {out / 'scalping_feasibility.csv'}")


if __name__ == "__main__":
    main()

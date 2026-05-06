"""
Parameter sweep for XAUUSD H1 momentum + trend filter strategy.
Uses walk-forward validation with corrected cost model.
"""
import os
import sys
from typing import Dict, List

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig
from backtest.walkforward import WalkForwardAnalysis
from backtest.metrics import calculate_metrics, print_metrics
from logger import setup_logger

logger = setup_logger("xauusd_sweep")


class MomentumTrendStrategy:
    """Simple momentum + optional trend filter."""
    
    def __init__(self, mom_lookback: int = 20, trend_lookback: int = 50, use_trend: bool = True):
        self.mom_lookback = mom_lookback
        self.trend_lookback = trend_lookback
        self.use_trend = use_trend
        self.name = f"MOM{mom_lookback}_TREND{trend_lookback if use_trend else 'OFF'}"
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        mom = close.pct_change(self.mom_lookback)
        
        long = mom > 0
        short = mom < 0
        
        if self.use_trend:
            trend_sma = close.rolling(self.trend_lookback).mean()
            long &= close > trend_sma
            short &= close < trend_sma
        
        signals = pd.Series(0, index=data.index, dtype=float)
        signals[long] = 1
        signals[short] = -1
        return signals


def run_sweep(data: pd.DataFrame, exec_cfg: ExecutionConfig) -> pd.DataFrame:
    """Run parameter sweep with walk-forward validation."""
    
    mom_lookbacks = [10, 15, 20, 30, 40, 50]
    trend_lookbacks = [0, 30, 50, 100, 200, 500]
    
    results = []
    total = len(mom_lookbacks) * len(trend_lookbacks)
    count = 0
    
    for mom in mom_lookbacks:
        for trend in trend_lookbacks:
            count += 1
            use_trend = trend > 0
            trend_lb = trend if use_trend else 50
            
            strategy = MomentumTrendStrategy(mom, trend_lb, use_trend)
            
            # Walk-forward: 3000 train, 1000 test
            wfa = WalkForwardAnalysis(
                data,
                lambda: strategy,
                train_size=3000,
                test_size=1000,
                execution_config=exec_cfg,
                periods_per_year=365 * 24,
            )
            
            try:
                combined = wfa.run(verbose=False)
                results.append({
                    "mom_lb": mom,
                    "trend_lb": trend_lb if use_trend else 0,
                    "sharpe": combined.get("sharpe_ratio", np.nan),
                    "total_return_pct": combined.get("total_return_pct", np.nan),
                    "ann_return_pct": combined.get("ann_return_pct", np.nan),
                    "ann_vol_pct": combined.get("ann_vol_pct", np.nan),
                    "max_dd_pct": combined.get("max_drawdown_pct", np.nan),
                    "num_trades": combined.get("num_trades", 0),
                    "win_rate_pct": combined.get("win_rate_pct", np.nan),
                    "profit_factor": combined.get("profit_factor", np.nan),
                    "windows": len(wfa.results),
                })
                logger.info(f"[{count}/{total}] MOM{mom} TREND{trend_lb if use_trend else 'OFF'}: "
                           f"Sharpe={combined.get('sharpe_ratio', 0):.3f} "
                           f"Ret={combined.get('total_return_pct', 0):.1f}% "
                           f"DD={combined.get('max_drawdown_pct', 0):.1f}% "
                           f"Trades={combined.get('num_trades', 0)}")
            except Exception as e:
                logger.error(f"[{count}/{total}] MOM{mom} TREND{trend_lb if use_trend else 'OFF'} failed: {e}")
                results.append({
                    "mom_lb": mom,
                    "trend_lb": trend_lb if use_trend else 0,
                    "sharpe": np.nan,
                    "error": str(e),
                })
    
    return pd.DataFrame(results)


def main():
    df = pd.read_parquet("data/raw/XAUUSD_H1.parquet")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    
    print(f"Loaded {len(df)} rows from {df['time'].min()} to {df['time'].max()}")
    print("=" * 80)
    print("XAUUSD MOMENTUM + TREND PARAMETER SWEEP")
    print("Cost model: spread from MT5 + $7/lot commission")
    print("=" * 80)
    
    # Use corrected execution config
    exec_cfg = ExecutionConfig(commission_per_lot=7.0, trade_lots=1.0)
    
    results = run_sweep(df, exec_cfg)
    results = results.sort_values("sharpe", ascending=False)
    
    print("\n" + "=" * 80)
    print("TOP 10 RESULTS BY SHARPE")
    print("=" * 80)
    print(results.head(10).to_string(index=False))
    
    os.makedirs("data/processed", exist_ok=True)
    results.to_csv("data/processed/xauusd_mom_trend_sweep.csv", index=False)
    print("\nSaved to data/processed/xauusd_mom_trend_sweep.csv")
    
    # Also show best strategy full metrics
    best = results.iloc[0]
    print(f"\nBest: MOM{best['mom_lb']} + TREND{best['trend_lb']} | Sharpe={best['sharpe']:.3f}")


if __name__ == "__main__":
    main()

"""
Parameter sweep for XAUUSD H4 momentum strategy.
"""
import os
import sys

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig
from backtest.walkforward import WalkForwardAnalysis
from backtest.metrics import print_metrics
from logger import setup_logger

logger = setup_logger("xauusd_h4_sweep")


class MomentumStrategy:
    def __init__(self, mom_lb=20, trend_lb=0):
        self.mom_lb = mom_lb
        self.trend_lb = trend_lb
        self.name = f"MOM{mom_lb}_TREND{trend_lb}"
    
    def generate_signals(self, data):
        close = data["close"]
        mom = close.pct_change(self.mom_lb)
        signals = pd.Series(0, index=data.index, dtype=float)
        
        long = mom > 0
        short = mom < 0
        
        if self.trend_lb > 0:
            sma = close.rolling(self.trend_lb).mean()
            long &= close > sma
            short &= close < sma
        
        signals[long] = 1
        signals[short] = -1
        return signals


def main():
    df = pd.read_parquet("data/raw/XAUUSD_H4.parquet")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    
    print(f"Loaded {len(df)} H4 bars from {df['time'].min()} to {df['time'].max()}")
    print("=" * 80)
    
    exec_cfg = ExecutionConfig(commission_per_lot=7.0, trade_lots=1.0)
    
    mom_lookbacks = [5, 10, 15, 20, 30, 40, 50]
    trend_lookbacks = [0, 20, 50, 100, 200]
    
    results = []
    for mom in mom_lookbacks:
        for trend in trend_lookbacks:
            strat = MomentumStrategy(mom, trend)
            wfa = WalkForwardAnalysis(
                df, lambda: strat,
                train_size=1000, test_size=500,
                execution_config=exec_cfg,
                periods_per_year=365*6,
            )
            try:
                combined = wfa.run(verbose=False)
                results.append({
                    "mom": mom,
                    "trend": trend,
                    "sharpe": combined.get("sharpe_ratio", np.nan),
                    "return_pct": combined.get("total_return_pct", np.nan),
                    "ann_ret": combined.get("ann_return_pct", np.nan),
                    "max_dd": combined.get("max_drawdown_pct", np.nan),
                    "windows": len(wfa.results),
                })
                logger.info(f"MOM{mom} TREND{trend}: Sharpe={combined.get('sharpe_ratio', 0):.3f} "
                           f"Ret={combined.get('total_return_pct', 0):.1f}% DD={combined.get('max_drawdown_pct', 0):.1f}%")
            except Exception as e:
                logger.error(f"MOM{mom} TREND{trend} failed: {e}")
    
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values("sharpe", ascending=False)
    
    print("\n" + "=" * 80)
    print("TOP RESULTS")
    print("=" * 80)
    print(results_df.head(15).to_string(index=False))
    
    # Also test on full sample
    print("\n" + "=" * 80)
    print("FULL SAMPLE BACKTEST: Best Strategy")
    print("=" * 80)
    best = results_df.iloc[0]
    best_strat = MomentumStrategy(int(best["mom"]), int(best["trend"]))
    bt = VectorizedBacktester(df, best_strat, execution_config=exec_cfg, periods_per_year=365*6)
    m = bt.run()
    print_metrics(m)
    
    os.makedirs("data/processed", exist_ok=True)
    results_df.to_csv("data/processed/xauusd_h4_sweep.csv", index=False)


if __name__ == "__main__":
    main()

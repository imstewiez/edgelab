"""
Test ensemble and adaptive momentum strategies across regimes.
"""
import os
import sys

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig
from backtest.metrics import print_metrics
from logger import setup_logger

logger = setup_logger("ensemble_test")


class SimpleMomentum:
    def __init__(self, lb):
        self.lb = lb
        self.name = f"MOM{lb}"
    def generate_signals(self, data):
        mom = data["close"].pct_change(self.lb)
        s = pd.Series(0, index=data.index, dtype=float)
        s[mom > 0] = 1
        s[mom < 0] = -1
        return s


class EnsembleMomentum:
    def __init__(self, lookbacks):
        self.lookbacks = lookbacks
        self.name = f"Ens{'+'.join(map(str, lookbacks))}"
    def generate_signals(self, data):
        moms = pd.DataFrame({lb: data["close"].pct_change(lb) for lb in self.lookbacks})
        avg_mom = moms.mean(axis=1)
        s = pd.Series(0, index=data.index, dtype=float)
        s[avg_mom > 0] = 1
        s[avg_mom < 0] = -1
        return s


class AdaptiveMomentum:
    def __init__(self, short=20, long=100, vol_period=20):
        self.short = short
        self.long = long
        self.vol_period = vol_period
        self.name = f"Adaptive{short}_{long}"
    def generate_signals(self, data):
        close = data["close"]
        mom_short = close.pct_change(self.short)
        mom_long = close.pct_change(self.long)
        log_ret = np.log(close / close.shift(1))
        vol = log_ret.rolling(self.vol_period).std() * np.sqrt(365 * 24)
        vol_pct = vol.rolling(100).rank(pct=True)
        weight_short = vol_pct.fillna(0.5)
        blended = weight_short * mom_short + (1 - weight_short) * mom_long
        s = pd.Series(0, index=data.index, dtype=float)
        s[blended > 0] = 1
        s[blended < 0] = -1
        return s


def test_on_data(path, label):
    df = pd.read_parquet(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    
    print(f"\n{'='*70}")
    print(f"{label} | {df['time'].min()} to {df['time'].max()}")
    print(f"{'='*70}")
    
    exec_cfg = ExecutionConfig(commission_per_lot=7.0, trade_lots=1.0)
    
    strategies = [
        SimpleMomentum(20),
        SimpleMomentum(40),
        SimpleMomentum(50),
        SimpleMomentum(80),
        SimpleMomentum(100),
        SimpleMomentum(120),
        EnsembleMomentum([20, 80, 120]),
        EnsembleMomentum([40, 80, 120]),
        EnsembleMomentum([20, 50, 100]),
        AdaptiveMomentum(20, 100),
        AdaptiveMomentum(20, 80),
    ]
    
    results = []
    for strat in strategies:
        bt = VectorizedBacktester(df, strat, execution_config=exec_cfg, periods_per_year=365*24)
        m = bt.run()
        results.append({
            "strategy": strat.name,
            "sharpe": round(m.get("sharpe_ratio", 0), 3),
            "return_pct": round(m.get("total_return_pct", 0), 1),
            "max_dd": round(m.get("max_drawdown_pct", 0), 1),
            "trades": m.get("num_trades", 0),
        })
        print(f"{strat.name:20s}: Sharpe={m.get('sharpe_ratio', 0):.3f}  Ret={m.get('total_return_pct', 0):6.1f}%  DD={m.get('max_drawdown_pct', 0):6.1f}%  Trades={m.get('num_trades', 0)}")
    
    return pd.DataFrame(results)


def main():
    r1 = test_on_data("data/raw/XAUUSD_H1.parquet", "2021-2026 MT5")
    r2 = test_on_data("data/external/XAUUSD_H1_dukascopy_3y.parquet", "2016-2019 Dukascopy")
    
    # Merge and compare
    merged = r1.merge(r2, on="strategy", suffixes=("_bull", "_sideways"))
    merged["avg_sharpe"] = round((merged["sharpe_bull"] + merged["sharpe_sideways"]) / 2, 3)
    merged["min_sharpe"] = round(merged[["sharpe_bull", "sharpe_sideways"]].min(axis=1), 3)
    merged = merged.sort_values("min_sharpe", ascending=False)
    
    print(f"\n{'='*70}")
    print("ROBUSTNESS RANKING (sorted by minimum Sharpe across regimes)")
    print(f"{'='*70}")
    print(merged[["strategy", "sharpe_bull", "sharpe_sideways", "avg_sharpe", "min_sharpe"]].to_string(index=False))


if __name__ == "__main__":
    main()

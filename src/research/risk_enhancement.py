"""
Test risk-management overlays on MOM100 to improve Sharpe and reduce drawdowns.
"""
import os
import sys

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig
from backtest.metrics import calculate_metrics, print_metrics
from logger import setup_logger

logger = setup_logger("risk_enhancement")


class BaseMOM100:
    """Base 100-bar momentum strategy."""
    def __init__(self):
        self.name = "MOM100"
    def generate_signals(self, data):
        mom = data["close"].pct_change(100)
        s = pd.Series(0, index=data.index, dtype=float)
        s[mom > 0] = 1
        s[mom < 0] = -1
        return s


class MOM100_VolTarget:
    """MOM100 with volatility targeting position sizing."""
    def __init__(self, target_vol=0.10, vol_lookback=20):
        self.target_vol = target_vol
        self.vol_lookback = vol_lookback
        self.name = f"MOM100_VolTarget{target_vol}"
    
    def generate_signals(self, data):
        close = data["close"]
        mom = close.pct_change(100)
        
        # Base signal
        s = pd.Series(0, index=data.index, dtype=float)
        s[mom > 0] = 1
        s[mom < 0] = -1
        
        # Volatility scaling
        log_ret = np.log(close / close.shift(1))
        realized_vol = log_ret.rolling(self.vol_lookback).std() * np.sqrt(365 * 24)
        size = self.target_vol / realized_vol
        size = size.fillna(0).clip(0.1, 1.5)  # More conservative cap than before
        
        return s * size


class MOM100_Threshold:
    """MOM100 with momentum threshold — flat when momentum is too small."""
    def __init__(self, threshold=0.001):
        self.threshold = threshold
        self.name = f"MOM100_Thresh{threshold}"
    
    def generate_signals(self, data):
        mom = data["close"].pct_change(100)
        s = pd.Series(0, index=data.index, dtype=float)
        s[mom > self.threshold] = 1
        s[mom < -self.threshold] = -1
        return s


class MOM100_VolAndThresh:
    """Combined: vol targeting + momentum threshold."""
    def __init__(self, target_vol=0.10, threshold=0.001, vol_lookback=20):
        self.target_vol = target_vol
        self.threshold = threshold
        self.vol_lookback = vol_lookback
        self.name = f"MOM100_Vol{target_vol}_Thresh{threshold}"
    
    def generate_signals(self, data):
        close = data["close"]
        mom = close.pct_change(100)
        
        s = pd.Series(0, index=data.index, dtype=float)
        s[mom > self.threshold] = 1
        s[mom < -self.threshold] = -1
        
        log_ret = np.log(close / close.shift(1))
        realized_vol = log_ret.rolling(self.vol_lookback).std() * np.sqrt(365 * 24)
        size = self.target_vol / realized_vol
        size = size.fillna(0).clip(0.1, 1.5)
        
        return s * size


class MOM100_SessionFilter:
    """MOM100 only during London + NY overlap (12:00-16:00 UTC)."""
    def __init__(self):
        self.name = "MOM100_Session"
    
    def generate_signals(self, data):
        mom = data["close"].pct_change(100)
        hour = pd.to_datetime(data["time"]).dt.hour if "time" in data.columns else data.index.hour
        
        s = pd.Series(0, index=data.index, dtype=float)
        # Only trade during active hours (avoid 22:00-07:00 UTC = Asian session)
        active = (hour >= 7) & (hour <= 22)
        s[(mom > 0) & active] = 1
        s[(mom < 0) & active] = -1
        return s


def run_comparison(path, label):
    df = pd.read_parquet(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    
    print(f"\n{'='*70}")
    print(f"RISK ENHANCEMENT TEST: {label}")
    print(f"{'='*70}")
    
    exec_cfg = ExecutionConfig(commission_per_lot=7.0, trade_lots=1.0)
    
    strategies = [
        BaseMOM100(),
        MOM100_VolTarget(target_vol=0.10),
        MOM100_VolTarget(target_vol=0.15),
        MOM100_Threshold(threshold=0.0005),
        MOM100_Threshold(threshold=0.001),
        MOM100_Threshold(threshold=0.002),
        MOM100_VolAndThresh(target_vol=0.10, threshold=0.001),
        MOM100_SessionFilter(),
    ]
    
    results = []
    for strat in strategies:
        bt = VectorizedBacktester(df, strat, execution_config=exec_cfg, periods_per_year=365*24)
        m = bt.run()
        results.append({
            "strategy": strat.name,
            "sharpe": round(m.get("sharpe_ratio", 0), 3),
            "return_pct": round(m.get("total_return_pct", 0), 1),
            "ann_ret": round(m.get("ann_return_pct", 0), 1),
            "ann_vol": round(m.get("ann_vol_pct", 0), 1),
            "max_dd": round(m.get("max_drawdown_pct", 0), 1),
            "trades": m.get("num_trades", 0),
            "win_rate": round(m.get("win_rate_pct", 0), 1),
            "pf": round(m.get("profit_factor", 0), 2),
        })
        print(f"{strat.name:25s}: Sharpe={m.get('sharpe_ratio', 0):.3f}  Ret={m.get('total_return_pct', 0):6.1f}%  "
              f"Vol={m.get('ann_vol_pct', 0):5.1f}%  DD={m.get('max_drawdown_pct', 0):6.1f}%  "
              f"Trades={m.get('num_trades', 0)}")
    
    return pd.DataFrame(results)


def main():
    r1 = run_comparison("data/raw/XAUUSD_H1.parquet", "2021-2026 MT5 (Bull)")
    r2 = run_comparison("data/external/XAUUSD_H1_dukascopy_3y.parquet", "2016-2019 Dukascopy (Sideways)")
    
    # Merge and rank by minimum Sharpe across regimes
    merged = r1.merge(r2, on="strategy", suffixes=("_bull", "_side"))
    merged["avg_sharpe"] = round((merged["sharpe_bull"] + merged["sharpe_side"]) / 2, 3)
    merged["min_sharpe"] = round(merged[["sharpe_bull", "sharpe_side"]].min(axis=1), 3)
    merged = merged.sort_values("min_sharpe", ascending=False)
    
    print(f"\n{'='*70}")
    print("ROBUSTNESS RANKING (by minimum Sharpe across regimes)")
    print(f"{'='*70}")
    print(merged[["strategy", "sharpe_bull", "sharpe_side", "avg_sharpe", "min_sharpe"]].to_string(index=False))
    
    os.makedirs("data/processed", exist_ok=True)
    merged.to_csv("data/processed/risk_enhancement_results.csv", index=False)


if __name__ == "__main__":
    main()

"""
Quick check: does MOM20 work on other assets and timeframes?
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

logger = setup_logger("multi_asset")


class MOM20Strategy:
    def __init__(self, mom_lookback=20):
        self.mom_lookback = mom_lookback
        self.name = f"MOM{mom_lookback}"
    
    def generate_signals(self, data):
        close = data["close"]
        mom = close.pct_change(self.mom_lookback)
        signals = pd.Series(0, index=data.index, dtype=float)
        signals[mom > 0] = 1
        signals[mom < 0] = -1
        return signals


def test_asset(symbol, timeframe):
    path = f"data/raw/{symbol}_{timeframe}.parquet"
    if not os.path.exists(path):
        return None
    
    df = pd.read_parquet(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    
    if len(df) < 4000:
        return None
    
    ppy_map = {"M1": 365*24*60, "M5": 365*24*12, "M15": 365*24*4,
               "H1": 365*24, "H4": 365*6, "D1": 365}
    ppy = ppy_map.get(timeframe, 365*24)
    
    exec_cfg = ExecutionConfig(commission_per_lot=7.0, trade_lots=1.0)
    strategy = MOM20Strategy(20)
    
    wfa = WalkForwardAnalysis(
        df,
        lambda: strategy,
        train_size=3000,
        test_size=1000,
        execution_config=exec_cfg,
        periods_per_year=ppy,
    )
    
    try:
        combined = wfa.run(verbose=False)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "sharpe": combined.get("sharpe_ratio", np.nan),
            "total_return_pct": combined.get("total_return_pct", np.nan),
            "ann_return_pct": combined.get("ann_return_pct", np.nan),
            "max_dd_pct": combined.get("max_drawdown_pct", np.nan),
            "num_trades": combined.get("num_trades", 0),
            "win_rate_pct": combined.get("win_rate_pct", np.nan),
            "profit_factor": combined.get("profit_factor", np.nan),
        }
    except Exception as e:
        logger.error(f"{symbol} {timeframe} failed: {e}")
        return None


def main():
    assets = [
        ("EURUSD", "H1"), ("EURUSD", "H4"), ("EURUSD", "D1"),
        ("XAUUSD", "H1"), ("XAUUSD", "H4"), ("XAUUSD", "D1"),
        ("NAS100", "H1"), ("NAS100", "H4"), ("NAS100", "D1"),
    ]
    
    results = []
    for symbol, tf in assets:
        logger.info(f"Testing {symbol} {tf}...")
        res = test_asset(symbol, tf)
        if res:
            results.append(res)
            logger.info(f"  Sharpe={res['sharpe']:.3f} | Return={res['total_return_pct']:.1f}% | DD={res['max_dd_pct']:.1f}%")
    
    df = pd.DataFrame(results)
    df = df.sort_values("sharpe", ascending=False)
    
    print("\n" + "=" * 80)
    print("MULTI-ASSET MOM20 RESULTS")
    print("=" * 80)
    print(df.to_string(index=False))
    
    os.makedirs("data/processed", exist_ok=True)
    df.to_csv("data/processed/multi_asset_mom20.csv", index=False)


if __name__ == "__main__":
    main()

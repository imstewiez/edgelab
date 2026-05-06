"""
Validate XAUUSD MOM20 strategy on Dukascopy 10-year data.
This script should be run after batch_dukascopy.py completes.
"""
import os
import sys

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig
from backtest.walkforward import WalkForwardAnalysis
from backtest.metrics import calculate_metrics, print_metrics
from logger import setup_logger

logger = setup_logger("validate_dukascopy")


class MomentumStrategy:
    def __init__(self, mom_lookback=100):
        self.mom_lookback = mom_lookback
        self.name = f"MOM{mom_lookback}"
    
    def generate_signals(self, data):
        mom = data["close"].pct_change(self.mom_lookback)
        signals = pd.Series(0, index=data.index, dtype=float)
        signals[mom > 0] = 1
        signals[mom < 0] = -1
        return signals


def validate_symbol(symbol, timeframe="H1"):
    """Run validation on Dukascopy data for a symbol."""
    path = f"data/external/{symbol}_{timeframe}_dukascopy.parquet"
    alt_path = f"data/external/{symbol}_{timeframe}_dukascopy_3y.parquet"
    if os.path.exists(alt_path):
        path = alt_path
    elif not os.path.exists(path):
        logger.error(f"File not found: {path}")
        return None
    
    df = pd.read_parquet(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    
    logger.info(f"Loaded {len(df)} {timeframe} bars for {symbol}")
    logger.info(f"Date range: {df['time'].min()} to {df['time'].max()}")
    
    if len(df) < 4000:
        logger.error(f"Insufficient data: {len(df)} bars")
        return None
    
    exec_cfg = ExecutionConfig(commission_per_lot=7.0, trade_lots=1.0)
    strategy = MomentumStrategy(100)
    
    # 1. Full sample backtest
    logger.info(f"Running full-sample backtest...")
    bt = VectorizedBacktester(df, strategy, execution_config=exec_cfg, periods_per_year=365*24)
    full_sample = bt.run()
    
    print(f"\n=== {symbol} {timeframe} FULL SAMPLE ===")
    print_metrics(full_sample)
    
    # 2. Walk-forward validation
    train_size = min(3000, len(df) // 3)
    test_size = min(1000, len(df) // 6)
    
    if train_size + test_size <= len(df):
        logger.info(f"Running walk-forward: train={train_size}, test={test_size}")
        wfa = WalkForwardAnalysis(
            df,
            lambda: strategy,
            train_size=train_size,
            test_size=test_size,
            execution_config=exec_cfg,
            periods_per_year=365*24,
        )
        wf_metrics = wfa.run(verbose=False)
        
        print(f"\n=== {symbol} {timeframe} WALK-FORWARD ===")
        print_metrics(wf_metrics)
    else:
        logger.warning("Insufficient data for walk-forward")
        wf_metrics = None
    
    # 3. Regime analysis: split into bull/bear/sideways
    df["returns"] = df["close"].pct_change()
    df["sma_200"] = df["close"].rolling(200).mean()
    
    bull = df["close"] > df["sma_200"] * 1.02
    bear = df["close"] < df["sma_200"] * 0.98
    sideways = ~(bull | bear)
    
    regimes = []
    for name, mask in [("bull", bull), ("bear", bear), ("sideways", sideways)]:
        regime_df = df[mask].copy()
        if len(regime_df) < 100:
            continue
        
        bt_regime = VectorizedBacktester(regime_df, strategy, execution_config=exec_cfg, periods_per_year=365*24)
        m = bt_regime.run()
        regimes.append({
            "regime": name,
            "bars": len(regime_df),
            "sharpe": m.get("sharpe_ratio", np.nan),
            "return_pct": m.get("total_return_pct", np.nan),
            "max_dd": m.get("max_drawdown_pct", np.nan),
        })
    
    if regimes:
        print(f"\n=== {symbol} {timeframe} REGIME BREAKDOWN ===")
        print(pd.DataFrame(regimes).to_string(index=False))
    
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "full_sample": full_sample,
        "walk_forward": wf_metrics,
        "regimes": regimes,
    }


def main():
    print("=" * 80)
    print("DUKASCOPY 10-YEAR VALIDATION")
    print("=" * 80)
    
    for symbol in ["XAUUSD", "EURUSD"]:
        result = validate_symbol(symbol, "H1")
        if result is None:
            print(f"\n{symbol}: Data not available yet. Skipping.")
    
    print("\n" + "=" * 80)
    print("VALIDATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()

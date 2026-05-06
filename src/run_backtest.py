#!/usr/bin/env python3
"""
Run backtests on available data.
Usage: python src/run_backtest.py --symbol EURUSD --timeframe H1 --strategy SMA
"""
import argparse
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.logger import setup_logger
from src.backtest.engine import VectorizedBacktester
from src.backtest.execution import ExecutionConfig
from src.backtest.metrics import print_metrics
from src.backtest.strategy import (
    BuyAndHold, SMAStrategy, RSIStrategy, MACDStrategy, BollingerStrategy
)
from src.backtest.walkforward import WalkForwardAnalysis

logger = setup_logger("run_backtest")

STRATEGIES = {
    "buyhold": BuyAndHold,
    "sma": lambda: SMAStrategy(fast=20, slow=50),
    "rsi": lambda: RSIStrategy(period=14, oversold=30, overbought=70),
    "macd": lambda: MACDStrategy(fast=12, slow=26, signal=9),
    "bb": lambda: BollingerStrategy(period=20, std_dev=2.0),
}


def load_data(symbol: str, timeframe: str) -> pd.DataFrame:
    """Load best available data (prefers longest history)."""
    candidates = []
    
    # Collect all available sources
    paths = [
        f"data/external/{symbol}_{timeframe}_dukascopy.parquet",
        f"data/external/{symbol}_{timeframe}_yahoo.parquet",
        f"data/raw/{symbol}_{timeframe}.parquet",
    ]
    
    for path in paths:
        if os.path.exists(path):
            df = pd.read_parquet(path)
            df["time"] = pd.to_datetime(df["time"], utc=True)
            df = df.sort_values("time").reset_index(drop=True)
            candidates.append((len(df), path, df))
    
    if not candidates:
        raise FileNotFoundError(f"No data found for {symbol} {timeframe}")
    
    # Pick the one with the most rows (longest history)
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_len, best_path, best_df = candidates[0]
    logger.info(f"Loading data from {best_path} ({best_len:,} rows)")
    logger.info(f"Range: {best_df['time'].min()} to {best_df['time'].max()}")
    return best_df


def main():
    parser = argparse.ArgumentParser(description="Run backtest on FX data")
    parser.add_argument("--symbol", default="EURUSD", help="Symbol to test")
    parser.add_argument("--timeframe", default="H1", help="Timeframe (M1, H1, D1, etc)")
    parser.add_argument("--strategy", default="sma", choices=list(STRATEGIES.keys()), help="Strategy to test")
    parser.add_argument("--walkforward", action="store_true", help="Run walk-forward analysis")
    parser.add_argument("--train-bars", type=int, default=2000, help="Training window size")
    parser.add_argument("--test-bars", type=int, default=500, help="Test window size")
    parser.add_argument("--capital", type=float, default=100_000.0, help="Initial capital")
    parser.add_argument("--commission", type=float, default=7.0, help="Commission per lot round-turn")
    args = parser.parse_args()
    
    # Load data
    try:
        data = load_data(args.symbol, args.timeframe)
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    
    # Setup execution config for ECN account
    exec_cfg = ExecutionConfig(
        commission_per_lot=args.commission,
        trade_lots=1.0
    )
    
    # Determine periods per year for annualization
    ppy_map = {"M1": 365*24*60, "M5": 365*24*12, "M15": 365*24*4, 
               "H1": 365*24, "H4": 365*6, "D1": 365}
    ppy = ppy_map.get(args.timeframe, 365*24)
    
    if args.walkforward:
        logger.info(f"Running walk-forward analysis: {args.strategy} on {args.symbol} {args.timeframe}")
        wfa = WalkForwardAnalysis(
            data,
            STRATEGIES[args.strategy],
            train_size=args.train_bars,
            test_size=args.test_bars,
            execution_config=exec_cfg,
            periods_per_year=ppy
        )
        wfa.run()
        
        # Save window summary
        summary = wfa.get_window_summary()
        out_path = f"data/processed/wfa_{args.symbol}_{args.timeframe}_{args.strategy}.csv"
        summary.to_csv(out_path, index=False)
        logger.info(f"Walk-forward summary saved to {out_path}")
    else:
        # Simple backtest
        strategy = STRATEGIES[args.strategy]()
        logger.info(f"Running backtest: {strategy.name} on {args.symbol} {args.timeframe}")
        
        bt = VectorizedBacktester(
            data,
            strategy,
            initial_capital=args.capital,
            execution_config=exec_cfg,
            periods_per_year=ppy
        )
        metrics = bt.run()
        print_metrics(metrics)
        
        # Save equity curve
        results = bt.get_results()
        equity_df = pd.DataFrame({
            "time": data["time"],
            "equity": results["equity_curve"].values,
            "position": results["positions"].values,
            "signal": results["signals"].values,
        })
        out_path = f"data/processed/equity_{args.symbol}_{args.timeframe}_{args.strategy}.csv"
        equity_df.to_csv(out_path, index=False)
        logger.info(f"Equity curve saved to {out_path}")
        
        # Save trades
        if results["trades"] is not None and len(results["trades"]) > 0:
            trades_path = f"data/processed/trades_{args.symbol}_{args.timeframe}_{args.strategy}.csv"
            results["trades"].to_csv(trades_path, index=False)
            logger.info(f"Trades saved to {trades_path}")


if __name__ == "__main__":
    main()

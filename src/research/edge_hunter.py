"""
Systematic edge hunting across FX and index data.
Tests multiple hypotheses with walk-forward validation and realistic costs.
"""
import json
import os
import sys
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig
from backtest.metrics import calculate_metrics
from backtest.walkforward import WalkForwardAnalysis
from logger import setup_logger

logger = setup_logger("edge_hunter")


class FeatureEngine:
    """Generate technical features for research."""
    
    @staticmethod
    def add_features(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close = df["close"]
        high = df["high"]
        low = df["low"]
        
        # Returns
        df["ret_1"] = close.pct_change()
        df["ret_5"] = close.pct_change(5)
        df["ret_10"] = close.pct_change(10)
        df["ret_20"] = close.pct_change(20)
        
        # Moving averages
        for period in [10, 20, 50, 100, 200]:
            df[f"sma_{period}"] = close.rolling(period).mean()
            df[f"ema_{period}"] = close.ewm(span=period, adjust=False).mean()
        
        # Distance from MAs
        df["dist_sma20"] = (close - df["sma_20"]) / df["sma_20"]
        df["dist_sma50"] = (close - df["sma_50"]) / df["sma_50"]
        
        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        for period in [7, 14, 21]:
            avg_gain = gain.rolling(period).mean()
            avg_loss = loss.rolling(period).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            df[f"rsi_{period}"] = 100 - (100 / (1 + rs))
        
        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        df["macd"] = ema12 - ema26
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]
        
        # Bollinger Bands
        for period in [20, 50]:
            mid = close.rolling(period).mean()
            std = close.rolling(period).std()
            df[f"bb_upper_{period}"] = mid + 2 * std
            df[f"bb_lower_{period}"] = mid - 2 * std
            df[f"bb_pct_{period}"] = (close - df[f"bb_lower_{period}"]) / (df[f"bb_upper_{period}"] - df[f"bb_lower_{period}"])
        
        # ATR and volatility
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        for period in [10, 20, 50]:
            df[f"atr_{period}"] = tr.rolling(period).mean()
            df[f"atr_pct_{period}"] = df[f"atr_{period}"] / close
        
        df["vol_regime"] = (df["atr_pct_20"] > df["atr_pct_20"].rolling(100).mean()).astype(int)
        
        # Donchian channels
        df["donchian_upper_20"] = high.rolling(20).max()
        df["donchian_lower_20"] = low.rolling(20).min()
        df["donchian_mid_20"] = (df["donchian_upper_20"] + df["donchian_lower_20"]) / 2
        
        # Momentum
        df["mom_10"] = close.pct_change(10)
        df["mom_20"] = close.pct_change(20)
        df["mom_50"] = close.pct_change(50)
        
        # Acceleration
        df["accel_10"] = df["mom_10"] - df["mom_10"].shift(5)
        
        # Session features (for H1 data)
        if pd.api.types.is_datetime64_any_dtype(df["time"]):
            df["hour"] = pd.to_datetime(df["time"]).dt.hour
            df["dayofweek"] = pd.to_datetime(df["time"]).dt.dayofweek
            # London open = 8 UTC, NY open = 13 UTC
            df["is_london"] = ((df["hour"] >= 7) & (df["hour"] <= 11)).astype(int)
            df["is_ny"] = ((df["hour"] >= 12) & (df["hour"] <= 16)).astype(int)
            df["is_asian"] = ((df["hour"] >= 0) & (df["hour"] <= 6)).astype(int)
        
        # Volume features if available
        if "tick_volume" in df.columns:
            df["vol_ratio"] = df["tick_volume"] / df["tick_volume"].rolling(20).mean()
        
        return df


class SignalStrategy:
    """Simple strategy from a signal function."""
    
    def __init__(self, name: str, signal_fn):
        self.name = name
        self.signal_fn = signal_fn
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        signals = self.signal_fn(data)
        if isinstance(signals, np.ndarray):
            signals = pd.Series(signals, index=data.index)
        return signals.reindex(data.index).fillna(0)


def build_strategies() -> List[Tuple[str, callable]]:
    """Build list of (name, signal_function) tuples to test."""
    strategies = []
    
    # 1. TREND FOLLOWING
    strategies.append(("TF_SMA20x50", lambda d: np.where(d["sma_20"] > d["sma_50"], 1, -1)))
    strategies.append(("TF_EMA20x50", lambda d: np.where(d["ema_20"] > d["ema_50"], 1, -1)))
    strategies.append(("TF_MACD", lambda d: np.where(d["macd"] > d["macd_signal"], 1, -1)))
    strategies.append(("TF_MOM20", lambda d: np.where(d["mom_20"] > 0, 1, -1)))
    strategies.append(("TF_Donchian20", lambda d: np.where(
        d["close"] > d["donchian_upper_20"].shift(1), 1,
        np.where(d["close"] < d["donchian_lower_20"].shift(1), -1, 0)
    )))
    
    # 2. MEAN REVERSION
    strategies.append(("MR_RSI14_30_70", lambda d: np.where(
        d["rsi_14"] < 30, 1, np.where(d["rsi_14"] > 70, -1, 0)
    )))
    strategies.append(("MR_BB20_pct", lambda d: np.where(
        d["bb_pct_20"] < 0.05, 1, np.where(d["bb_pct_20"] > 0.95, -1, 0)
    )))
    strategies.append(("MR_DistSMA20", lambda d: np.where(
        d["dist_sma20"] < -0.02, 1, np.where(d["dist_sma20"] > 0.02, -1, 0)
    )))
    
    # 3. VOLATILITY BREAKOUT
    strategies.append(("VOL_Break_ATR", lambda d: np.where(
        d["close"] > d["close"].shift(1) + 1.5 * d["atr_20"].shift(1), 1,
        np.where(d["close"] < d["close"].shift(1) - 1.5 * d["atr_20"].shift(1), -1, 0)
    )))
    strategies.append(("VOL_Squeeze", lambda d: np.where(
        (d["atr_pct_20"] < d["atr_pct_20"].rolling(50).mean() * 0.8) & 
        (d["close"] > d["bb_upper_20"].shift(1)), 1,
        np.where(
            (d["atr_pct_20"] < d["atr_pct_20"].rolling(50).mean() * 0.8) & 
            (d["close"] < d["bb_lower_20"].shift(1)), -1, 0
        )
    )))
    
    # 4. REGIME-CONDITIONAL
    # Trend only in high vol
    strategies.append(("Regime_TF_HighVol", lambda d: np.where(
        (d["vol_regime"] == 1) & (d["sma_20"] > d["sma_50"]), 1,
        np.where((d["vol_regime"] == 1) & (d["sma_20"] < d["sma_50"]), -1, 0)
    )))
    # MR only in low vol
    strategies.append(("Regime_MR_LowVol", lambda d: np.where(
        (d["vol_regime"] == 0) & (d["rsi_14"] < 30), 1,
        np.where((d["vol_regime"] == 0) & (d["rsi_14"] > 70), -1, 0)
    )))
    
    # 5. SESSION-BASED (H1 only)
    strategies.append(("Session_London_MOM", lambda d: np.where(
        (d["is_london"] == 1) & (d["mom_10"] > 0.005), 1,
        np.where((d["is_london"] == 1) & (d["mom_10"] < -0.005), -1, 0)
    )))
    strategies.append(("Session_NY_Continuation", lambda d: np.where(
        (d["is_ny"] == 1) & (d["mom_10"] > 0.003), 1,
        np.where((d["is_ny"] == 1) & (d["mom_10"] < -0.003), -1, 0)
    )))
    
    # 6. COMPOSITE
    strategies.append(("Composite_MOM_RSI", lambda d: np.where(
        (d["mom_20"] > 0) & (d["rsi_14"] > 50), 1,
        np.where((d["mom_20"] < 0) & (d["rsi_14"] < 50), -1, 0)
    )))
    strategies.append(("Composite_MACD_Vol", lambda d: np.where(
        (d["macd_hist"] > 0) & (d["vol_regime"] == 1), 1,
        np.where((d["macd_hist"] < 0) & (d["vol_regime"] == 1), -1, 0)
    )))
    
    return strategies


def run_research(
    data: pd.DataFrame,
    symbol: str,
    timeframe: str,
    train_bars: int = 3000,
    test_bars: int = 1000,
    min_sharpe: float = 0.0,
    max_dd: float = -50.0
) -> pd.DataFrame:
    """
    Run full research sweep on a dataset.
    Returns DataFrame of promising strategies sorted by out-of-sample Sharpe.
    """
    logger.info(f"Research sweep on {symbol} {timeframe} | {len(data)} bars")
    
    # Add features
    data = FeatureEngine.add_features(data)
    
    # Drop rows with too many NaNs
    data = data.dropna(subset=["sma_20", "rsi_14", "atr_20", "macd"])
    
    if len(data) < train_bars + test_bars:
        logger.warning(f"Insufficient data after feature engineering: {len(data)}")
        return pd.DataFrame()
    
    strategies = build_strategies()
    results = []
    
    exec_cfg = ExecutionConfig(commission_per_lot=7.0, trade_lots=1.0)
    ppy_map = {"M1": 365*24*60, "M5": 365*24*12, "M15": 365*24*4,
               "H1": 365*24, "H4": 365*6, "D1": 365}
    ppy = ppy_map.get(timeframe, 365*24)
    
    logger.info(f"Testing {len(strategies)} strategies...")
    
    for name, signal_fn in strategies:
        try:
            strategy = SignalStrategy(name, signal_fn)
            
            # Walk-forward analysis
            wfa = WalkForwardAnalysis(
                data,
                lambda: strategy,
                train_size=train_bars,
                test_size=test_bars,
                execution_config=exec_cfg,
                periods_per_year=ppy
            )
            combined = wfa.run(verbose=False)
            
            sharpe = combined.get("sharpe_ratio", -999)
            maxdd = combined.get("max_drawdown_pct", -999)
            total_ret = combined.get("total_return_pct", -999)
            
            if sharpe >= min_sharpe and maxdd >= max_dd:
                results.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "strategy": name,
                    "sharpe": sharpe,
                    "total_return_pct": total_ret,
                    "ann_return_pct": combined.get("ann_return_pct"),
                    "ann_vol_pct": combined.get("ann_vol_pct"),
                    "max_drawdown_pct": maxdd,
                    "num_trades": combined.get("num_trades", 0),
                    "win_rate_pct": combined.get("win_rate_pct", 0),
                    "windows": len(wfa.results),
                })
                
        except Exception as e:
            logger.debug(f"Strategy {name} failed: {e}")
            continue
    
    if not results:
        logger.info("No strategies met minimum criteria.")
        return pd.DataFrame()
    
    df = pd.DataFrame(results)
    df = df.sort_values("sharpe", ascending=False).reset_index(drop=True)
    return df


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--timeframe", default="H1")
    parser.add_argument("--min-sharpe", type=float, default=0.0)
    parser.add_argument("--output", default="data/processed/research_results.csv")
    args = parser.parse_args()
    
    # Load best available data (prefer longest history)
    candidates = []
    paths = [
        f"data/external/{args.symbol}_{args.timeframe}_dukascopy.parquet",
        f"data/external/{args.symbol}_{args.timeframe}_yahoo.parquet",
        # Yahoo uses 1d/1h instead of D1/H1
        f"data/external/{args.symbol}_1{args.timeframe.lower().replace('1', '')}_yahoo.parquet",
        f"data/raw/{args.symbol}_{args.timeframe}.parquet",
    ]
    for path in paths:
        if os.path.exists(path):
            df = pd.read_parquet(path)
            if "time" in df.columns:
                df["time"] = pd.to_datetime(df["time"], utc=True)
            elif isinstance(df.index, pd.DatetimeIndex):
                df = df.reset_index().rename(columns={"index": "time"})
            candidates.append((len(df), path, df))
    
    if not candidates:
        logger.error(f"No data found for {args.symbol} {args.timeframe}")
        sys.exit(1)
    
    candidates.sort(key=lambda x: x[0], reverse=True)
    _, best_path, data = candidates[0]
    logger.info(f"Using {best_path} ({len(data)} rows)")
    
    data = data.sort_values("time").reset_index(drop=True)
    
    results = run_research(data, args.symbol, args.timeframe, min_sharpe=args.min_sharpe)
    
    if not results.empty:
        print("\n" + "=" * 100)
        print("TOP STRATEGIES BY OUT-OF-SAMPLE SHARPE RATIO")
        print("=" * 100)
        print(results.to_string(index=False))
        print("=" * 100)
        
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        results.to_csv(args.output, index=False)
        logger.info(f"Results saved to {args.output}")
    else:
        print("\nNo strategies passed the minimum Sharpe threshold on out-of-sample data.")
        print("This is normal. Most simple strategies fail after realistic costs.")


if __name__ == "__main__":
    main()

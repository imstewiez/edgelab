"""
Broad strategy sweep across timeframes to find ANY positive-Sharpe edges on XAUUSD.
Tests trend, mean-reversion, breakout, pattern, and multi-timeframe strategies.
"""
import os
import sys

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig
from backtest.walkforward import WalkForwardAnalysis
from research.edge_hunter import FeatureEngine
from logger import setup_logger

logger = setup_logger("broad_sweep")


def build_all_strategies():
    """Build a comprehensive list of strategy lambdas."""
    strategies = []
    
    # === TREND FOLLOWING (various lookbacks) ===
    for lb in [10, 20, 50, 100, 150, 200]:
        strategies.append((f"MOM{lb}", lambda d, l=lb: np.where(d["close"].pct_change(l) > 0, 1, -1)))
    
    for fast, slow in [(10,30), (20,50), (20,100), (50,100), (50,200)]:
        strategies.append((f"SMA{fast}x{slow}", lambda d, f=fast, s=slow: np.where(d["close"].rolling(f).mean() > d["close"].rolling(s).mean(), 1, -1)))
    
    # === MEAN REVERSION ===
    for lookback in [20, 50, 100]:
        strategies.append((f"MR_zscore{lookback}", lambda d, l=lookback: _zscore_strategy(d, l)))
    
    strategies.append(("MR_RSI30_70", lambda d: np.where(d["rsi_14"] < 30, 1, np.where(d["rsi_14"] > 70, -1, 0))))
    strategies.append(("MR_BB_pct", lambda d: np.where(d["bb_pct_20"] < 0.05, 1, np.where(d["bb_pct_20"] > 0.95, -1, 0))))
    
    # === BREAKOUT ===
    strategies.append(("Breakout_20", lambda d: _breakout(d, 20)))
    strategies.append(("Breakout_50", lambda d: _breakout(d, 50)))
    strategies.append(("Breakout_100", lambda d: _breakout(d, 100)))
    strategies.append(("VolSqueeze_20", lambda d: _vol_squeeze(d, 20)))
    
    # === PATTERN-BASED ===
    strategies.append(("Consecutive_3", lambda d: _consecutive_bars(d, 3)))
    strategies.append(("Consecutive_5", lambda d: _consecutive_bars(d, 5)))
    strategies.append(("Engulfing", lambda d: _engulfing(d)))
    strategies.append(("InsideBar_Break", lambda d: _inside_bar_break(d)))
    
    # === MULTI-TIMEFRAME PROXY ===
    strategies.append(("MTF_H1H4", lambda d: _mtf_proxy(d, 4)))
    strategies.append(("MTF_H1D1", lambda d: _mtf_proxy(d, 24)))
    
    # === RANGE-BOUND DETECTION ===
    strategies.append(("RangeBreak_20", lambda d: _range_break(d, 20)))
    strategies.append(("RangeMeanRev_20", lambda d: _range_mean_rev(d, 20)))
    
    return strategies


def _zscore_strategy(data, lookback):
    z = (data["close"] - data["close"].rolling(lookback).mean()) / data["close"].rolling(lookback).std()
    return np.where(z < -1.5, 1, np.where(z > 1.5, -1, 0))


def _breakout(data, lookback):
    hh = data["high"].rolling(lookback).max().shift(1)
    ll = data["low"].rolling(lookback).min().shift(1)
    return np.where(data["close"] > hh, 1, np.where(data["close"] < ll, -1, 0))


def _vol_squeeze(data, lookback):
    atr_pct = (data["high"] - data["low"]).rolling(lookback).mean() / data["close"]
    atr_low = atr_pct < atr_pct.rolling(lookback*3).mean() * 0.8
    hh = data["high"].rolling(lookback).max().shift(1)
    ll = data["low"].rolling(lookback).min().shift(1)
    return np.where(atr_low & (data["close"] > hh), 1, np.where(atr_low & (data["close"] < ll), -1, 0))


def _consecutive_bars(data, n):
    up = (data["close"] > data["open"]).astype(int)
    down = (data["close"] < data["open"]).astype(int)
    consec_up = up.rolling(n).sum() == n
    consec_down = down.rolling(n).sum() == n
    return np.where(consec_up, 1, np.where(consec_down, -1, 0))


def _engulfing(data):
    prev_bull = data["close"].shift(1) > data["open"].shift(1)
    prev_bear = data["close"].shift(1) < data["open"].shift(1)
    bull_eng = (data["close"] > data["open"]) & (data["open"] < data["close"].shift(1)) & (data["close"] > data["open"].shift(1)) & prev_bear
    bear_eng = (data["close"] < data["open"]) & (data["open"] > data["close"].shift(1)) & (data["close"] < data["open"].shift(1)) & prev_bull
    return np.where(bull_eng, 1, np.where(bear_eng, -1, 0))


def _inside_bar_break(data):
    inside = (data["high"] < data["high"].shift(1)) & (data["low"] > data["low"].shift(1))
    return np.where(inside & (data["close"] > data["high"].shift(1)), 1, np.where(inside & (data["close"] < data["low"].shift(1)), -1, 0))


def _mtf_proxy(data, mult):
    """Simulate higher-TF alignment by checking momentum on scaled lookback."""
    mom_h1 = data["close"].pct_change(100)
    mom_hf = data["close"].pct_change(100 * mult)
    return np.where((mom_h1 > 0) & (mom_hf > 0), 1, np.where((mom_h1 < 0) & (mom_hf < 0), -1, 0))


def _range_break(data, lookback):
    """Breakout after range contraction."""
    range_pct = (data["high"].rolling(lookback).max() - data["low"].rolling(lookback).min()) / data["close"]
    range_contracted = range_pct < range_pct.rolling(lookback*3).mean() * 0.7
    hh = data["high"].rolling(lookback).max().shift(1)
    ll = data["low"].rolling(lookback).min().shift(1)
    return np.where(range_contracted & (data["close"] > hh), 1, np.where(range_contracted & (data["close"] < ll), -1, 0))


def _range_mean_rev(data, lookback):
    """Mean reversion within a range."""
    hh = data["high"].rolling(lookback).max()
    ll = data["low"].rolling(lookback).min()
    mid = (hh + ll) / 2
    return np.where(data["close"] < mid * 0.995, 1, np.where(data["close"] > mid * 1.005, -1, 0))


class SignalStrategy:
    def __init__(self, name, signal_fn):
        self.name = name
        self.signal_fn = signal_fn
    def generate_signals(self, data):
        sig = self.signal_fn(data)
        if isinstance(sig, np.ndarray):
            sig = pd.Series(sig, index=data.index)
        return sig.reindex(data.index).fillna(0)


def test_timeframe(symbol, timeframe):
    path = f"data/raw/{symbol}_{timeframe}.parquet"
    if not os.path.exists(path):
        return None
    
    df = pd.read_parquet(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    
    # Add features for strategies that need them
    df = FeatureEngine.add_features(df)
    df = df.dropna(subset=["rsi_14", "bb_pct_20"])
    
    if len(df) < 4000:
        return None
    
    ppy_map = {"M1": 365*24*60, "M5": 365*24*12, "M15": 365*24*4, "H1": 365*24, "H4": 365*6, "D1": 365}
    ppy = ppy_map.get(timeframe, 365*24)
    exec_cfg = ExecutionConfig(commission_per_lot=7.0, trade_lots=1.0)
    
    strategies = build_all_strategies()
    results = []
    
    logger.info(f"Testing {len(strategies)} strategies on {symbol} {timeframe} ({len(df)} bars)")
    
    for name, signal_fn in strategies:
        try:
            strat = SignalStrategy(name, signal_fn)
            wfa = WalkForwardAnalysis(df, lambda: strat, train_size=3000, test_size=1000, execution_config=exec_cfg, periods_per_year=ppy)
            combined = wfa.run(verbose=False)
            sharpe = combined.get("sharpe_ratio", -999)
            if sharpe >= 0.3:  # Only log promising ones
                results.append({
                    "symbol": symbol, "timeframe": timeframe, "strategy": name,
                    "sharpe": sharpe, "return_pct": combined.get("total_return_pct"),
                    "max_dd": combined.get("max_drawdown_pct"),
                    "trades": combined.get("num_trades", 0),
                })
                logger.info(f"  {name}: Sharpe={sharpe:.3f}")
        except Exception as e:
            logger.debug(f"{name} failed: {e}")
    
    return pd.DataFrame(results)


def main():
    all_results = []
    for tf in ["H1", "H4", "D1"]:
        res = test_timeframe("XAUUSD", tf)
        if res is not None and len(res) > 0:
            all_results.append(res)
    
    if all_results:
        df = pd.concat(all_results, ignore_index=True)
        df = df.sort_values("sharpe", ascending=False)
        print("\n" + "="*80)
        print("ALL POSITIVE-SHAPE STRATEGIES (Sharpe >= 0.3)")
        print("="*80)
        print(df.to_string(index=False))
        df.to_csv("data/processed/broad_sweep_results.csv", index=False)
    else:
        print("No strategies with Sharpe >= 0.3 found.")


if __name__ == "__main__":
    main()

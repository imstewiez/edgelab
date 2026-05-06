"""
Refined XAUUSD H1 trend-following strategy.
Uses vectorized backtester with proper stop logic and realistic XAUUSD costs.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd

from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig, ExecutionSimulator
from backtest.metrics import calculate_metrics, print_metrics


class XAUUSDTrendStrategy:
    """
    Refined XAUUSD trend strategy.
    
    Base signal: 20-bar momentum
    Filters:
      - Daily trend (1200-bar SMA alignment)
      - Volatility regime (ATR > rolling mean)
    Exit: Chandelier trailing stop (3x ATR from recent high/low)
    """
    
    def __init__(
        self,
        momentum_lookback: int = 20,
        trend_lookback: int = 1200,
        atr_period: int = 20,
        atr_vol_lookback: int = 100,
        chandelier_period: int = 22,
        chandelier_mult: float = 3.0,
        use_trend_filter: bool = True,
        use_vol_filter: bool = True,
        use_chandelier_stop: bool = True,
    ):
        self.momentum_lookback = momentum_lookback
        self.trend_lookback = trend_lookback
        self.atr_period = atr_period
        self.atr_vol_lookback = atr_vol_lookback
        self.chandelier_period = chandelier_period
        self.chandelier_mult = chandelier_mult
        self.use_trend_filter = use_trend_filter
        self.use_vol_filter = use_vol_filter
        self.use_chandelier_stop = use_chandelier_stop
        self.name = self._build_name()
    
    def _build_name(self) -> str:
        parts = ["XAU_Trend"]
        if self.use_trend_filter:
            parts.append("TrendFilt")
        if self.use_vol_filter:
            parts.append("VolFilt")
        if self.use_chandelier_stop:
            parts.append("ChandStop")
        return "_".join(parts)
    
    def add_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add all required features."""
        data = df.copy()
        close = data["close"]
        high = data["high"]
        low = data["low"]
        
        # Momentum
        data["mom"] = close.pct_change(self.momentum_lookback)
        
        # Trend proxy (~50 trading days)
        data["trend_sma"] = close.rolling(self.trend_lookback).mean()
        data["above_trend"] = close > data["trend_sma"]
        
        # ATR
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        data["atr"] = tr.rolling(self.atr_period).mean()
        data["atr_mean"] = data["atr"].rolling(self.atr_vol_lookback).mean()
        data["high_vol"] = data["atr"] > data["atr_mean"]
        
        # Chandelier stops (lagged by 1 bar to avoid lookahead)
        data["hh"] = high.rolling(self.chandelier_period).max().shift(1)
        data["ll"] = low.rolling(self.chandelier_period).min().shift(1)
        data["atr_lag"] = data["atr"].shift(1)
        data["chandelier_long"] = data["hh"] - self.chandelier_mult * data["atr_lag"]
        data["chandelier_short"] = data["ll"] + self.chandelier_mult * data["atr_lag"]
        
        return data
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """Generate base signals with filters."""
        data = self.add_features(data)
        
        long_cond = data["mom"] > 0
        short_cond = data["mom"] < 0
        
        if self.use_trend_filter:
            long_cond &= data["above_trend"]
            short_cond &= ~data["above_trend"]
        
        if self.use_vol_filter:
            long_cond &= data["high_vol"]
            short_cond &= data["high_vol"]
        
        signals = pd.Series(0, index=data.index)
        signals[long_cond] = 1
        signals[short_cond] = -1
        return signals
    
    def apply_stops(self, data: pd.DataFrame, positions: pd.Series) -> pd.Series:
        """Apply chandelier stops to position series (vectorized)."""
        if not self.use_chandelier_stop:
            return positions
        
        data = self.add_features(data)
        pos = positions.copy()
        
        # Exit longs when close drops below chandelier level
        long_stop = (pos == 1) & (data["close"] < data["chandelier_long"])
        # Exit shorts when close rises above chandelier level
        short_stop = (pos == -1) & (data["close"] > data["chandelier_short"])
        
        pos[long_stop | short_stop] = 0
        return pos
    
    def run_backtest(self, data: pd.DataFrame, initial_capital: float = 100_000.0) -> dict:
        """Run full backtest using VectorizedBacktester."""
        data = self.add_features(data).dropna()
        
        # Custom execution config for XAUUSD
        # XAUUSD: 1 lot = 100 oz, spread ~0.20, commission $7/lot
        # Notional at 2300 = 230,000
        # Round-turn cost ≈ 0.20/2300 + 7/230000 = 0.0087% + 0.0030% = 0.0117%
        exec_cfg = ExecutionConfig(
            spread_pips=20,  # 20 points = 0.20 for 2-digit gold
            commission_per_lot=7.0,
            lot_size=100,  # 100 oz per lot
            trade_lots=1.0,
            pip_value=1.0,  # $1 per point per lot for XAUUSD
        )
        
        bt = VectorizedBacktester(
            data,
            self,
            initial_capital=initial_capital,
            execution_config=exec_cfg,
            periods_per_year=365 * 24
        )
        metrics = bt.run()
        
        return {
            "metrics": metrics,
            "equity_curve": bt.equity_curve,
            "positions": bt.positions,
            "signals": bt.signals,
            "trades": bt.trades,
            "data": data,
        }


def compare_variants(data: pd.DataFrame):
    """Compare strategy variants."""
    variants = [
        ("Base Momentum", XAUUSDTrendStrategy(
            use_trend_filter=False, use_vol_filter=False, use_chandelier_stop=False
        )),
        ("+ Trend Filter", XAUUSDTrendStrategy(
            use_trend_filter=True, use_vol_filter=False, use_chandelier_stop=False
        )),
        ("+ Vol Filter", XAUUSDTrendStrategy(
            use_trend_filter=False, use_vol_filter=True, use_chandelier_stop=False
        )),
        ("+ Both Filters", XAUUSDTrendStrategy(
            use_trend_filter=True, use_vol_filter=True, use_chandelier_stop=False
        )),
        ("+ Chandelier Stop", XAUUSDTrendStrategy(
            use_trend_filter=True, use_vol_filter=True, use_chandelier_stop=True
        )),
    ]
    
    results = []
    for name, strat in variants:
        res = strat.run_backtest(data)
        m = res["metrics"]
        trades = res["trades"]
        results.append({
            "variant": name,
            "sharpe": round(m.get("sharpe_ratio", 0), 3),
            "total_return_pct": round(m.get("total_return_pct", 0), 2),
            "ann_return_pct": round(m.get("ann_return_pct", 0), 2),
            "ann_vol_pct": round(m.get("ann_vol_pct", 0), 2),
            "max_dd_pct": round(m.get("max_drawdown_pct", 0), 2),
            "num_trades": len(trades) if trades is not None else 0,
            "win_rate_pct": round(m.get("win_rate_pct", 0), 1),
            "profit_factor": round(m.get("profit_factor", 0), 2),
        })
    
    return pd.DataFrame(results)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/raw/XAUUSD_H1.parquet")
    args = parser.parse_args()
    
    df = pd.read_parquet(args.data)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    
    print(f"Loaded {len(df)} rows from {df['time'].min()} to {df['time'].max()}")
    print("\n" + "=" * 90)
    print("XAUUSD REFINED STRATEGY COMPARISON")
    print("=" * 90)
    
    summary = compare_variants(df)
    print("\n" + summary.to_string(index=False))
    
    os.makedirs("data/processed", exist_ok=True)
    summary.to_csv("data/processed/xauusd_refinement.csv", index=False)
    print("\nSaved to data/processed/xauusd_refinement.csv")

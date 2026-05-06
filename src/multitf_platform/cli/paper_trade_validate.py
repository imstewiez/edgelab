"""Validate paper broker against vectorized backtest baseline.

Runs event-driven simulation with SAME parameters as vectorized backtest:
- Fixed $100k equity for risk wrapper (circuit breakers don't trigger)
- Ignore position_scale (full size like vectorized)
- Same cost model

Goal: produce similar results to vectorized backtest.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np

from multitf_platform.strategy.frozen.v1_0_0 import MultiTFStrategy, FrozenStrategyConfig
from multitf_platform.risk.v1_1 import RiskWrapper
from multitf_platform.brokers.paper import PaperBroker
from multitf_platform.config.models import PlatformConfig, BrokerConfig


def run_validation():
    base = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    
    h1 = pd.read_parquet(base / "XAUUSD_H1.parquet")
    if "time" in h1.columns:
        h1.set_index("time", inplace=True)
    
    h4 = pd.read_parquet(base / "XAUUSD_H4.parquet")
    if "time" in h4.columns:
        h4.set_index("time", inplace=True)
    
    # Match vectorized backtest parameters
    platform_cfg = PlatformConfig()
    broker_cfg = BrokerConfig(
        initial_equity=100000.0,  # Match vectorized notional
        leverage=1000,
        commission_per_lot=7.0,
        min_lot_size=0.01,
        lot_step=0.01,
        slippage_pips_mean=0.0,  # No slippage for baseline comparison
        slippage_pips_std=0.0,
    )
    
    strategy = MultiTFStrategy(FrozenStrategyConfig())
    risk = RiskWrapper(platform_cfg.risk_wrapper)
    broker = PaperBroker(broker_cfg)
    
    # Force paper broker to use fixed lot size (like vectorized 1.0 lot)
    # We'll override _calculate_lot_size behavior by monkey-patching
    def fixed_lot_size(self, decision, bar):
        # Ignore scale for baseline comparison (vectorized ignores scale)
        return 1.0
    broker._calculate_lot_size = fixed_lot_size.__get__(broker, PaperBroker)
    
    print("Simulating (validation mode, matching vectorized params)...")
    
    for i, ts in enumerate(h1.index):
        if i < 500:
            continue
        
        h1_slice = h1.iloc[:i+1]
        h4_slice = h4[h4.index <= ts]
        bar = h1.iloc[i]
        
        sig = strategy.generate_signal(h1_slice, h4_slice, ts)
        
        # Fixed equity like vectorized backtest
        wrapped = risk.apply(sig, h1_slice, 100000.0, 20.0)
        
        broker.process_bar(wrapped, bar, i)
    
    # Metrics
    ec = broker.get_equity_curve()
    returns = ec.pct_change().dropna()
    ann_ret = returns.mean() * 252 * 24 * 100
    ann_vol = returns.std() * np.sqrt(252 * 24) * 100
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    
    peak = ec.expanding().max()
    dd = (ec - peak) / peak
    max_dd = dd.min() * 100
    
    stats = broker.get_trade_stats()
    
    print(f"\n{'='*60}")
    print("EVENT-DRIVEN PAPER BROKER (Validation Mode)")
    print(f"{'='*60}")
    print(f"Sharpe:          {sharpe:.3f}")
    print(f"Ann Return:      {ann_ret:.1f}%")
    print(f"Max DD:          {max_dd:.1f}%")
    print(f"Trades:          {stats['total_trades']}")
    print(f"Win Rate:        {stats['win_rate']*100:.1f}%")
    print(f"Final Equity:    ${ec.iloc[-1]:,.2f}")
    
    print(f"\n{'='*60}")
    print("VECTORIZED BACKTEST (Reference)")
    print(f"{'='*60}")
    print(f"Sharpe:          2.050")
    print(f"Ann Return:      20.7%")
    print(f"Max DD:          -5.4%")
    print(f"Trades:          483")


if __name__ == "__main__":
    run_validation()

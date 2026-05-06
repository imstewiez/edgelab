"""Backtest MultiTF with risk wrapper integrated into vectorized engine."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from multitf_platform.strategy.frozen.v1_0_0 import MultiTFStrategy, FrozenStrategyConfig
from multitf_platform.risk.v1_1 import RiskWrapper
from multitf_platform.config.models import PlatformConfig, RiskWrapperConfig
from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig


def run_backtest_with_risk(symbol="XAUUSD", enable_risk=True):
    base = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    
    h1 = pd.read_parquet(base / f"{symbol}_H1.parquet")
    if "time" in h1.columns:
        h1.set_index("time", inplace=True)
    
    h4 = pd.read_parquet(base / f"{symbol}_H4.parquet")
    if "time" in h4.columns:
        h4.set_index("time", inplace=True)
    
    # Generate raw signals
    strategy = MultiTFStrategy(FrozenStrategyConfig())
    raw_signals = strategy.generate_signals_series(h1, h4)
    
    if enable_risk:
        # Apply risk wrapper to each bar
        config = PlatformConfig()
        risk = RiskWrapper(config.risk_wrapper)
        
        adjusted_signals = pd.Series(0, index=h1.index, dtype=float)
        
        for i, ts in enumerate(h1.index):
            if i < 500:  # Skip warmup
                continue
            
            h1_slice = h1.iloc[:i+1]
            h4_slice = h4[h4.index <= ts]
            
            sig = strategy.generate_signal(h1_slice, h4_slice, ts)
            
            spread = 20.0  # Assume 20 points typical spread
            equity = 100000.0  # Notional equity
            
            wrapped = risk.apply(sig, h1_slice, equity, spread)
            # Only use direction, not scale (scale applied via position sizing)
            adjusted_signals.iloc[i] = wrapped.final_direction
        
        signals = adjusted_signals
    else:
        signals = raw_signals
    
    # Run through vectorized backtester
    cfg = ExecutionConfig(spread_pips=0.2, commission_per_lot=7.0, lot_size=100.0, trade_lots=1.0, slippage_pips=0.0, pip_value=1.0)
    
    class MockStrategy:
        def __init__(self, sig):
            self.sig = sig
        def generate_signals(self, data):
            return self.sig.reindex(data.index).fillna(0)
    
    bt = VectorizedBacktester(h1, MockStrategy(signals), execution_config=cfg)
    bt.run()
    
    from backtest.metrics import calculate_metrics
    metrics = calculate_metrics(bt.equity_curve, trades=bt.trades, periods_per_year=252*24)
    
    return metrics, bt, raw_signals, signals


if __name__ == "__main__":
    print("=" * 70)
    print("MultiTF v1.0.0 + Risk Wrapper v1.1 Backtest")
    print("=" * 70)
    
    print("\n--- WITHOUT RISK CONTROLS ---")
    m_base, bt_base, raw_sig, _ = run_backtest_with_risk(enable_risk=False)
    print(f"Sharpe: {m_base.get('sharpe_ratio', 0):.3f}")
    print(f"Ann Ret: {m_base.get('ann_return_pct', 0):.1f}%")
    print(f"Max DD: {m_base.get('max_drawdown_pct', 0):.1f}%")
    print(f"Trades: {m_base.get('num_trades', 0)}")
    
    print("\n--- WITH RISK WRAPPER v1.1 ---")
    m_risk, bt_risk, _, adj_sig = run_backtest_with_risk(enable_risk=True)
    print(f"Sharpe: {m_risk.get('sharpe_ratio', 0):.3f}")
    print(f"Ann Ret: {m_risk.get('ann_return_pct', 0):.1f}%")
    print(f"Max DD: {m_risk.get('max_drawdown_pct', 0):.1f}%")
    print(f"Trades: {m_risk.get('num_trades', 0)}")
    
    print("\n--- COMPARISON ---")
    print(f"Sharpe change: {m_risk.get('sharpe_ratio', 0) - m_base.get('sharpe_ratio', 0):+.3f}")
    print(f"Return change: {m_risk.get('ann_return_pct', 0) - m_base.get('ann_return_pct', 0):+.1f}%")
    print(f"DD change: {abs(m_risk.get('max_drawdown_pct', 0)) - abs(m_base.get('max_drawdown_pct', 0)):+.1f}%")

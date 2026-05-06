"""Paper trading simulation using event-driven execution with PaperBroker.

This simulates the full pipeline:
  Data → Signal → Risk Wrapper → Paper Broker → Fills

Produces realistic equity curves with spread, slippage, commission, and margin.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np

from multitf_platform.strategy.frozen.v1_0_0 import MultiTFStrategy, FrozenStrategyConfig
from multitf_platform.risk.v1_1 import RiskWrapper
from multitf_platform.brokers.paper import PaperBroker
from multitf_platform.config.models import PlatformConfig, BrokerConfig, RiskWrapperConfig, CircuitBreakerConfig


def run_paper_trade_backtest(symbol="XAUUSD"):
    """Run event-driven backtest with paper broker simulation."""
    base = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    
    h1 = pd.read_parquet(base / f"{symbol}_H1.parquet")
    if "time" in h1.columns:
        h1.set_index("time", inplace=True)
    
    h4 = pd.read_parquet(base / f"{symbol}_H4.parquet")
    if "time" in h4.columns:
        h4.set_index("time", inplace=True)
    
    # Configs - max out circuit breakers for backtest validation
    # (circuit breakers are validated separately; here we test execution costs)
    from multitf_platform.config.models import CircuitBreakerConfig
    risk_cfg = RiskWrapperConfig(
        circuit_breakers=CircuitBreakerConfig(
            daily_loss_stop_pct=20.0,       # Max allowed
            weekly_loss_stop_pct=30.0,      # Max allowed
            monthly_loss_stop_pct=50.0,     # Max allowed
            total_drawdown_warning_pct=50.0, # Max allowed
            total_drawdown_kill_pct=50.0,    # Max allowed
        )
    )
    # $300 demo account with realistic slippage
    broker_cfg = BrokerConfig(
        initial_equity=300.0,
        leverage=1000,
        commission_per_lot=7.0,
        min_lot_size=0.01,
        slippage_pips_mean=0.5,
        slippage_pips_std=0.3,
    )
    
    # Components
    strategy = MultiTFStrategy(FrozenStrategyConfig())
    risk = RiskWrapper(risk_cfg)
    broker = PaperBroker(broker_cfg)
    
    # Bar-by-bar simulation
    print(f"Simulating {len(h1)} bars...")
    
    for i, ts in enumerate(h1.index):
        if i < 500:  # Warmup
            continue
        
        h1_slice = h1.iloc[:i+1]
        h4_slice = h4[h4.index <= ts]
        bar = h1.iloc[i]
        
        # 1. Generate signal
        sig = strategy.generate_signal(h1_slice, h4_slice, ts)
        
        # 2. Apply risk wrapper
        spread = 0.20  # $0.20 typical XAUUSD ECN spread
        equity = broker.get_state().equity
        
        wrapped = risk.apply(sig, h1_slice, equity, spread)
        
        # 3. Execute via paper broker
        broker.process_bar(wrapped, bar, i)
    
    # Results
    equity_curve = broker.get_equity_curve()
    stats = broker.get_trade_stats()
    
    returns = equity_curve.pct_change().dropna()
    ann_return = returns.mean() * 252 * 24 * 100
    ann_vol = returns.std() * np.sqrt(252 * 24) * 100
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0
    
    peak = equity_curve.expanding().max()
    drawdown = (equity_curve - peak) / peak
    max_dd = drawdown.min() * 100
    
    return {
        "equity_curve": equity_curve,
        "sharpe": sharpe,
        "ann_return": ann_return,
        "max_dd": max_dd,
        "trades": stats["total_trades"],
        "win_rate": stats["win_rate"] * 100,
        "avg_pnl": stats["avg_pnl"],
        "broker": broker,
    }


if __name__ == "__main__":
    print("=" * 70)
    print("MultiTF v1.0.0 + Risk v1.1 + Paper Broker Event-Driven Backtest")
    print("=" * 70)
    
    results = run_paper_trade_backtest()
    
    print(f"\nFinal Equity:    ${results['equity_curve'].iloc[-1]:.2f}")
    print(f"Sharpe Ratio:     {results['sharpe']:.3f}")
    print(f"Ann. Return:      {results['ann_return']:.1f}%")
    print(f"Max Drawdown:     {results['max_dd']:.1f}%")
    print(f"Total Trades:     {results['trades']}")
    print(f"Win Rate:         {results['win_rate']:.1f}%")
    print(f"Avg P&L/Trade:    ${results['avg_pnl']:.2f}")
    
    print("\n" + "=" * 70)
    print("Paper broker simulation complete.")
    print("=" * 70)

"""Trace execution of first N bars to find the trade blocker."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd

from multitf_platform.strategy.frozen.v1_0_0 import MultiTFStrategy, FrozenStrategyConfig
from multitf_platform.risk.v1_1 import RiskWrapper
from multitf_platform.brokers.paper import PaperBroker
from multitf_platform.config.models import RiskWrapperConfig, CircuitBreakerConfig, BrokerConfig


def trace_execution(symbol="XAUUSD", n_bars=200):
    base = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    
    h1 = pd.read_parquet(base / f"{symbol}_H1.parquet")
    if "time" in h1.columns:
        h1.set_index("time", inplace=True)
    
    h4 = pd.read_parquet(base / f"{symbol}_H4.parquet")
    if "time" in h4.columns:
        h4.set_index("time", inplace=True)
    
    risk_cfg = RiskWrapperConfig(
        circuit_breakers=CircuitBreakerConfig(
            daily_loss_stop_pct=5.0,
            weekly_loss_stop_pct=10.0,
            monthly_loss_stop_pct=20.0,
            total_drawdown_warning_pct=20.0,
            total_drawdown_kill_pct=50.0,
        )
    )
    broker_cfg = BrokerConfig(initial_equity=10300.0, leverage=1000)
    
    strategy = MultiTFStrategy(FrozenStrategyConfig())
    risk = RiskWrapper(risk_cfg)
    broker = PaperBroker(broker_cfg)
    
    print(f"{'Bar':>4} | {'Timestamp':>16} | {'Raw':>3} | {'Action':>8} | {'Scale':>5} | {'Target':>6} | {'Pos':>4} | {'Lots':>6} | {'Equity':>8}")
    print("-" * 90)
    
    trade_count = 0
    
    for i in range(500, 500 + n_bars):
        ts = h1.index[i]
        h1_slice = h1.iloc[:i+1]
        h4_slice = h4[h4.index <= ts]
        bar = h1.iloc[i]
        
        sig = strategy.generate_signal(h1_slice, h4_slice, ts)
        equity = broker.get_state().equity
        
        wrapped = risk.apply(sig, h1_slice, equity, 0.25)
        
        pos_before = broker.position.direction if broker.position else 0
        pos_size_before = broker.position.size_lots if broker.position else 0.0
        
        broker.process_bar(wrapped, bar, i)
        
        pos_after = broker.position.direction if broker.position else 0
        
        if pos_before != pos_after:
            trade_count += 1
            marker = "***"
        else:
            marker = ""
        
        if trade_count <= 10 and pos_before != pos_after:
            print(f"{i:>4} | {str(ts):>16} | {sig.direction:>3} | {wrapped.action.name:>8} | {wrapped.position_scale:>5.2f} | {wrapped.final_direction:>6} | {pos_after:>4} | {broker.position.size_lots if broker.position else 0:>6.2f} | {equity:>8.2f} {marker}")
    
    print(f"\nTotal trades in {n_bars} bars: {trade_count}")
    print(f"Final equity: ${broker.get_state().equity:.2f}")


if __name__ == "__main__":
    trace_execution(n_bars=500)

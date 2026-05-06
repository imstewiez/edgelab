"""Debug script to trace risk wrapper decisions."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from collections import Counter

from multitf_platform.strategy.frozen.v1_0_0 import MultiTFStrategy, FrozenStrategyConfig
from multitf_platform.risk.v1_1 import RiskWrapper
from multitf_platform.config.models import RiskWrapperConfig, CircuitBreakerConfig


def debug_risk_decisions(symbol="XAUUSD", n_bars=1000):
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
    
    strategy = MultiTFStrategy(FrozenStrategyConfig())
    risk = RiskWrapper(risk_cfg)
    
    action_counts = Counter()
    reason_counts = Counter()
    raw_signal_counts = Counter()
    
    start_idx = 500
    end_idx = min(start_idx + n_bars, len(h1))
    
    for i in range(start_idx, end_idx):
        ts = h1.index[i]
        h1_slice = h1.iloc[:i+1]
        h4_slice = h4[h4.index <= ts]
        
        sig = strategy.generate_signal(h1_slice, h4_slice, ts)
        raw_signal_counts[sig.direction] += 1
        
        spread = 0.25
        equity = 300.0
        
        wrapped = risk.apply(sig, h1_slice, equity, spread)
        action_counts[wrapped.action.name] += 1
        if wrapped.reason:
            reason_counts[wrapped.reason.split(":")[0]] += 1
    
    print("Raw signal distribution:")
    for d, c in sorted(raw_signal_counts.items()):
        print(f"  Direction {d}: {c} ({c/n_bars*100:.1f}%)")
    
    print("\nRisk wrapper action distribution:")
    for a, c in sorted(action_counts.items()):
        print(f"  {a}: {c} ({c/n_bars*100:.1f}%)")
    
    print("\nTop reasons:")
    for r, c in reason_counts.most_common(10):
        print(f"  {r}: {c}")


if __name__ == "__main__":
    debug_risk_decisions(n_bars=2000)

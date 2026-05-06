"""Compare vectorized vs event-driven signal generation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np

from multitf_platform.strategy.frozen.v1_0_0 import MultiTFStrategy, FrozenStrategyConfig


def compare():
    base = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    
    h1 = pd.read_parquet(base / "XAUUSD_H1.parquet")
    if "time" in h1.columns:
        h1.set_index("time", inplace=True)
    
    h4 = pd.read_parquet(base / "XAUUSD_H4.parquet")
    if "time" in h4.columns:
        h4.set_index("time", inplace=True)
    
    strategy = MultiTFStrategy(FrozenStrategyConfig())
    
    # Vectorized signals
    vec_signals = strategy.generate_signals_series(h1, h4)
    
    # Event-driven signals (first 1000 bars after warmup)
    evt_signals = pd.Series(0, index=h1.index[500:1500])
    for i, ts in enumerate(h1.index[500:1500]):
        h1_slice = h1.iloc[:500+i+1]
        h4_slice = h4[h4.index <= ts]
        sig = strategy.generate_signal(h1_slice, h4_slice, ts)
        evt_signals.iloc[i] = sig.direction
    
    # Compare
    vec_subset = vec_signals.reindex(evt_signals.index).fillna(0)
    
    matches = (vec_subset == evt_signals).sum()
    total = len(evt_signals)
    
    print(f"Signal match rate: {matches}/{total} ({matches/total*100:.1f}%)")
    print(f"\nVectorized distribution: {vec_subset.value_counts().to_dict()}")
    print(f"Event-driven distribution: {evt_signals.value_counts().to_dict()}")
    
    # Show mismatches
    mismatches = vec_subset != evt_signals
    if mismatches.any():
        print(f"\nFirst 10 mismatches:")
        for ts in mismatches[mismatches].index[:10]:
            print(f"  {ts}: vec={vec_subset[ts]}, evt={evt_signals[ts]}")


if __name__ == "__main__":
    compare()

"""Quick test: verify base MOM100 works with project's backtest engine."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from backtest.strategy import Strategy
from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig

class MOM100(Strategy):
    def __init__(self, lookback=100):
        super().__init__(f"MOM{lookback}")
        self.lookback = lookback
    
    def generate_signals(self, data):
        mom = data["close"].pct_change(self.lookback)
        return pd.Series(np.where(mom > 0, 1, np.where(mom < 0, -1, 0)), index=data.index)

# Load XAUUSD
import numpy as np
df = pd.read_parquet("data/raw/XAUUSD_H1.parquet")
if "time" in df.columns:
    df.set_index("time", inplace=True)

print(f"Data: {len(df)} bars, {df.index[0]} to {df.index[-1]}")
print(f"Price range: {df['close'].min():.2f} - {df['close'].max():.2f}")

# Config for XAUUSD
config = ExecutionConfig(
    spread_pips=None,  # Use data spread
    commission_per_lot=7.0,
    lot_size=100.0,
    trade_lots=1.0,
    slippage_pips=0.0,
    pip_value=1.0,  # $1 per point for XAUUSD? Actually $0.01 per point per oz, so 100 oz = $1 per point
)

strategy = MOM100(lookback=100)
bt = VectorizedBacktester(df, strategy, execution_config=config)
metrics = bt.run()

print("\nBase MOM100 on full data:")
for k, v in metrics.items():
    print(f"  {k}: {v}")

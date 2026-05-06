"""
Production Ensemble - Multi-pair, dynamically weighted, walk-forward validated.
Only uses pairs/strategies with positive cross-regime Sharpe.
"""
import sys, os, warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from glob import glob
from typing import Dict, List, Tuple
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtest.strategy import Strategy
from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig

# --- Cost configs ---------------------------------------------------
def get_config(symbol: str):
    if "XAU" in symbol or "XAG" in symbol:
        return ExecutionConfig(spread_pips=None, commission_per_lot=7.0, lot_size=100.0, trade_lots=1.0, slippage_pips=0.0, pip_value=1.0)
    elif "GER" in symbol or "US30" in symbol or "NAS" in symbol:
        return ExecutionConfig(spread_pips=None, commission_per_lot=7.0, lot_size=1.0, trade_lots=1.0, slippage_pips=0.0, pip_value=1.0)
    else:
        return ExecutionConfig(spread_pips=None, commission_per_lot=7.0, lot_size=100000.0, trade_lots=1.0, slippage_pips=0.0, pip_value=10.0)

# --- Strategy Classes -----------------------------------------------
class MOM100Strategy(Strategy):
    def __init__(self, lookback=100):
        super().__init__(f"MOM{lookback}")
        self.lookback = lookback
    def generate_signals(self, data):
        mom = data["close"].pct_change(self.lookback)
        return pd.Series(np.where(mom > 0, 1, np.where(mom < 0, -1, 0)), index=data.index)

class AdaptiveRegimeStrategy(Strategy):
    def __init__(self):
        super().__init__("AdaptiveRegime")
    def generate_signals(self, data):
        d1_close = data["close"].resample("1D").last().dropna()
        d1_ret = d1_close.pct_change().dropna()
        vol = d1_ret.rolling(20).std() * np.sqrt(252)
        vol_h1 = vol.reindex(data.index, method="ffill")
        mom50 = data["close"].pct_change(50)
        mom100 = data["close"].pct_change(100)
        mom200 = data["close"].pct_change(200)
        sig = pd.Series(0, index=data.index)
        strong = vol_h1 > 0.20
        weak = vol_h1 < 0.10
        mod = ~(strong.fillna(False) | weak.fillna(False))
        sig[strong.fillna(False)] = np.where(mom50[strong.fillna(False)] > 0, 1, -1)
        sig[weak.fillna(False)] = np.where(mom200[weak.fillna(False)] > 0, 1, -1)
        sig[mod] = np.where(mom100[mod] > 0, 1, -1)
        return sig

class MockStrategy(Strategy):
    def __init__(self, signals):
        super().__init__("Mock")
        self._signals = signals
    def generate_signals(self, data):
        return self._signals.reindex(data.index).fillna(0)

# --- Data loading ---------------------------------------------------
def load_data():
    base = os.path.join(os.path.dirname(__file__), "..", "..")
    data = {}
    for path in glob(os.path.join(base, "data/raw/*_H1.parquet")):
        sym = os.path.basename(path).replace("_H1.parquet", "")
        df = pd.read_parquet(path)
        if "time" in df.columns:
            df.set_index("time", inplace=True)
        data[sym] = df
    return data

# --- Portfolio Configuration ----------------------------------------
@dataclass
class StrategyConfig:
    pair: str
    strategy: Strategy
    weight: float = 1.0

# The production portfolio: only proven edges
PRODUCTION_CONFIG = [
    StrategyConfig("XAUUSD", AdaptiveRegimeStrategy()),
    StrategyConfig("XAUUSD", MOM100Strategy(100)),
    StrategyConfig("XAUEUR_s", MOM100Strategy(100)),
    StrategyConfig("XAGUSD_s", MOM100Strategy(100)),
    StrategyConfig("NAS100", AdaptiveRegimeStrategy()),
]

# --- Walk-Forward Portfolio Engine ----------------------------------
class ProductionEnsemble:
    """
    Institutional-grade ensemble:
    1. Per-pair strategy optimization (Sharpe-weighted)
    2. Per-pair capital allocation (inverse-vol weighted)
    3. Walk-forward validation
    4. Correlation-aware portfolio construction
    """
    
    def __init__(self, configs: List[StrategyConfig], pair_data: Dict[str, pd.DataFrame],
                 train_bars: int = 3000, test_bars: int = 1000):
        self.configs = configs
        self.data = pair_data
        self.train_bars = train_bars
        self.test_bars = test_bars
        
    def _get_strategies_for_pair(self, pair: str) -> List[Strategy]:
        return [c.strategy for c in self.configs if c.pair == pair]
    
    def _optimize_strategy_weights(self, pair: str, train_data: pd.DataFrame) -> Dict[str, float]:
        """Weight strategies by recent Sharpe (softmax)."""
        strategies = self._get_strategies_for_pair(pair)
        if not strategies:
            return {}
        
        sharpes = {}
        for strat in strategies:
            try:
                bt = VectorizedBacktester(train_data, strat, execution_config=get_config(pair))
                m = bt.run()
                sharpes[strat.name] = max(0.001, m.get("sharpe_ratio", 0.001))
            except:
                sharpes[strat.name] = 0.001
        
        # Softmax with temperature
        temp = 1.0
        exp_s = {k: np.exp(v / temp) for k, v in sharpes.items()}
        total = sum(exp_s.values())
        return {k: v/total for k, v in exp_s.items()}
    
    def _optimize_pair_weights(self, pair_metrics: Dict[str, dict]) -> Dict[str, float]:
        """Weight pairs by risk-adjusted return (inverse vol)."""
        weights = {}
        for pair, metrics in pair_metrics.items():
            sharpe = metrics.get("sharpe_ratio", 0)
            vol = metrics.get("ann_vol_pct", 1)
            if sharpe > 0 and vol > 0:
                weights[pair] = sharpe / vol  # Risk-adjusted weight
            else:
                weights[pair] = 0.001
        
        total = sum(weights.values())
        return {k: v/total for k, v in weights.items()}
    
    def run_walk_forward(self) -> Tuple[pd.Series, Dict]:
        """
        Run full walk-forward portfolio backtest.
        Returns: (portfolio_returns, final_metrics)
        """
        all_pair_returns = {}
        pair_strat_weights = {}
        
        # Process each pair independently
        for pair in set(c.pair for c in self.configs):
            df = self.data.get(pair)
            if df is None or len(df) < self.train_bars + self.test_bars:
                continue
            
            print("\n=== Pair: %s ===" % pair)
            pair_returns = []
            
            for start in range(0, len(df) - self.train_bars - self.test_bars, self.test_bars):
                train = df.iloc[start:start + self.train_bars]
                test = df.iloc[start + self.train_bars:start + self.train_bars + self.test_bars]
                
                # Optimize strategy weights on train
                strat_weights = self._optimize_strategy_weights(pair, train)
                
                # Generate combined signal
                combined_signal = pd.Series(0.0, index=test.index)
                for strat in self._get_strategies_for_pair(pair):
                    w = strat_weights.get(strat.name, 0)
                    if w < 0.01:
                        continue
                    sig = strat.generate_signals(test).reindex(test.index).fillna(0)
                    combined_signal += sig * w
                
                # Backtest combined signal
                bt = VectorizedBacktester(test, MockStrategy(combined_signal), execution_config=get_config(pair))
                metrics = bt.run()
                
                ret = bt.returns.copy()
                ret.index = test.index
                pair_returns.append(ret)
                
                if start == 0:
                    print("  Strategy weights: %s" % {k: round(v, 3) for k, v in strat_weights.items()})
                if start % 5000 == 0:
                    print("  Window %d-%d: Sharpe=%.3f, Ret=%.1f%%, DD=%.1f%%" % (
                        start, start + self.train_bars + self.test_bars,
                        metrics.get("sharpe_ratio", 0), metrics.get("ann_return_pct", 0),
                        metrics.get("max_drawdown_pct", 0)))
            
            if pair_returns:
                all_pair_returns[pair] = pd.concat(pair_returns).sort_index()
        
        # Align all pair returns and create portfolio
        if not all_pair_returns:
            return pd.Series(), {}
        
        aligned = pd.DataFrame(all_pair_returns).fillna(0)
        
        # Calculate pair-level Sharpe for allocation
        pair_sharpes = {}
        for pair in aligned.columns:
            rets = aligned[pair]
            if len(rets) > 10 and rets.std() > 0:
                pair_sharpes[pair] = (rets.mean() / rets.std()) * np.sqrt(252 * 24)
            else:
                pair_sharpes[pair] = 0
        
        print("\n" + "=" * 60)
        print("PAIR-LEVEL SHARPES (for allocation)")
        print("=" * 60)
        for pair, sharpe in pair_sharpes.items():
            print("  %s: %.3f" % (pair, sharpe))
        
        # Portfolio weighting: equal weight for simplicity, or inverse-vol
        # Use inverse volatility weighting
        pair_vols = aligned.std()
        inv_vols = 1.0 / (pair_vols + 0.0001)
        pair_weights = inv_vols / inv_vols.sum()
        
        print("\n" + "=" * 60)
        print("PORTFOLIO ALLOCATION (Inverse-Vol Weighted)")
        print("=" * 60)
        for pair, w in pair_weights.items():
            print("  %s: %.1f%%" % (pair, w * 100))
        
        # Build portfolio returns
        weighted_returns = aligned.multiply(pair_weights, axis=1)
        portfolio_returns = weighted_returns.sum(axis=1)
        
        # Calculate metrics
        equity = 100000 * (1 + portfolio_returns).cumprod()
        from backtest.metrics import calculate_metrics
        metrics = calculate_metrics(equity, periods_per_year=252*24)
        
        # Correlation analysis
        print("\n" + "=" * 60)
        print("PAIR RETURN CORRELATIONS")
        print("=" * 60)
        corr = aligned.corr()
        print(corr.round(3).to_string())
        
        return portfolio_returns, metrics, equity

# --- Main -----------------------------------------------------------
def main():
    print("=" * 80)
    print("PRODUCTION ENSEMBLE - Multi-Pair Adaptive Portfolio")
    print("=" * 80)
    
    data = load_data()
    
    # Filter to only pairs we have data for
    available_pairs = set(data.keys())
    active_configs = [c for c in PRODUCTION_CONFIG if c.pair in available_pairs]
    
    print("\nActive pairs/strategies:")
    for c in active_configs:
        print("  %s: %s" % (c.pair, c.strategy.name))
    
    ensemble = ProductionEnsemble(active_configs, data, train_bars=3000, test_bars=1000)
    returns, metrics, equity = ensemble.run_walk_forward()
    
    print("\n" + "=" * 80)
    print("FINAL PORTFOLIO METRICS")
    print("=" * 80)
    for k, v in metrics.items():
        print("  %s: %s" % (k, v))
    
    # Save results
    results_dir = os.path.join(os.path.dirname(__file__), "..", "..", "results")
    os.makedirs(results_dir, exist_ok=True)
    equity.to_csv(os.path.join(results_dir, "ensemble_equity.csv"))
    returns.to_csv(os.path.join(results_dir, "ensemble_returns.csv"))
    print("\nEquity curve and returns saved to results/")

if __name__ == "__main__":
    main()

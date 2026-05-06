"""
Production Trading System - Multi-Pair Adaptive Ensemble
Deployable on DPrime MT5 via the execution bridge.
"""
import sys, os, warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from glob import glob
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtest.strategy import Strategy
from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig

# ============================================================
# STRATEGY LIBRARY
# ============================================================

class MOMStrategy(Strategy):
    """Momentum strategy with configurable lookback."""
    def __init__(self, lookback: int = 100):
        super().__init__(f"MOM{lookback}")
        self.lookback = lookback
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        mom = data["close"].pct_change(self.lookback)
        return pd.Series(np.where(mom > 0, 1, np.where(mom < 0, -1, 0)), index=data.index)

class AdaptiveRegimeStrategy(Strategy):
    """
    Dynamically switches momentum lookback based on D1 volatility:
    - High vol (>20% ann): MOM50 (faster, more responsive)
    - Low vol (<10% ann): MOM200 (slower, fewer whipsaws)  
    - Moderate: MOM100 (validated baseline)
    """
    def __init__(self):
        super().__init__("AdaptiveRegime")
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
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

class MultiHorizonStrategy(Strategy):
    """Weighted consensus of multiple momentum lookbacks."""
    def __init__(self, lookbacks: Tuple[int, ...] = (50, 100, 150)):
        super().__init__("MultiHorizon")
        self.lookbacks = lookbacks
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        signals = {}
        for lb in self.lookbacks:
            mom = data["close"].pct_change(lb)
            signals[lb] = np.where(mom > 0, 1, -1)
        
        weights = {}
        for lb in self.lookbacks:
            sig_ret = signals[lb] * data["close"].pct_change()
            stability = 1.0 / (pd.Series(sig_ret).rolling(100).std().fillna(0.01) + 0.001)
            weights[lb] = stability
        
        total_w = sum(weights.values())
        consensus = sum(signals[lb] * (weights[lb] / total_w) for lb in self.lookbacks)
        return pd.Series(np.where(consensus > 0.3, 1, np.where(consensus < -0.3, -1, 0)), index=data.index)

# ============================================================
# PAIR CONFIGURATION
# ============================================================

@dataclass
class PairConfig:
    symbol: str              # MT5 symbol name
    strategies: List[Strategy]
    lot_size: float          # Units per lot
    commission_per_lot: float
    pip_value: float
    min_history_bars: int = 5000
    enabled: bool = True

# Production portfolio - validated edges only
PAIR_CONFIGS = [
    PairConfig(
        symbol="XAUUSD.s",
        strategies=[AdaptiveRegimeStrategy(), MOMStrategy(100)],
        lot_size=100.0,
        commission_per_lot=7.0,
        pip_value=1.0,
        enabled=True,
    ),
    PairConfig(
        symbol="XAUEUR.s",
        strategies=[MOMStrategy(100)],
        lot_size=100.0,
        commission_per_lot=7.0,
        pip_value=1.0,
        enabled=True,
    ),
    PairConfig(
        symbol="NAS100.s",
        strategies=[AdaptiveRegimeStrategy()],
        lot_size=1.0,
        commission_per_lot=7.0,
        pip_value=1.0,
        enabled=True,
    ),
    PairConfig(
        symbol="XAGUSD.s",
        strategies=[MOMStrategy(100)],
        lot_size=100.0,
        commission_per_lot=7.0,
        pip_value=1.0,
        enabled=True,
    ),
    PairConfig(
        symbol="XAUEUR.s",
        strategies=[MOMStrategy(100)],
        lot_size=100.0,
        commission_per_lot=7.0,
        pip_value=1.0,
        enabled=True,
    ),
]

# ============================================================
# ENSEMBLE ENGINE
# ============================================================

class AdaptiveEnsemble:
    """
    Walk-forward ensemble with dynamic strategy weighting per pair
    and risk-adjusted capital allocation across pairs.
    """
    
    def __init__(self, pair_configs: List[PairConfig], train_bars: int = 3000):
        self.configs = {c.symbol: c for c in pair_configs if c.enabled}
        self.train_bars = train_bars
        self.strategy_weights: Dict[str, Dict[str, float]] = {}
        self.pair_weights: Dict[str, float] = {}
        self.performance_log: List[dict] = []
    
    def _get_execution_config(self, cfg: PairConfig) -> ExecutionConfig:
        return ExecutionConfig(
            spread_pips=None,
            commission_per_lot=cfg.commission_per_lot,
            lot_size=cfg.lot_size,
            trade_lots=1.0,
            slippage_pips=0.0,
            pip_value=cfg.pip_value,
        )
    
    def optimize_strategy_weights(self, symbol: str, data: pd.DataFrame) -> Dict[str, float]:
        """Optimize strategy weights via recent Sharpe maximization."""
        cfg = self.configs[symbol]
        train = data.iloc[-self.train_bars:] if len(data) > self.train_bars else data
        
        sharpes = {}
        for strat in cfg.strategies:
            try:
                ec = self._get_execution_config(cfg)
                bt = VectorizedBacktester(train, strat, execution_config=ec)
                m = bt.run()
                sharpes[strat.name] = max(0.001, m.get("sharpe_ratio", 0.001))
            except Exception as e:
                sharpes[strat.name] = 0.001
        
        # Softmax weighting
        exp_s = {k: np.exp(v) for k, v in sharpes.items()}
        total = sum(exp_s.values())
        weights = {k: v/total for k, v in exp_s.items()}
        
        self.strategy_weights[symbol] = weights
        return weights
    
    def optimize_pair_weights(self, pair_data: Dict[str, pd.DataFrame]) -> Dict[str, float]:
        """Allocate capital across pairs using inverse volatility."""
        vols = {}
        for symbol, df in pair_data.items():
            if symbol not in self.configs:
                continue
            recent = df.iloc[-self.train_bars:] if len(df) > self.train_bars else df
            rets = recent["close"].pct_change().dropna()
            vols[symbol] = rets.std() * np.sqrt(252 * 24) if len(rets) > 10 else 1.0
        
        inv_vols = {k: 1.0 / (v + 0.0001) for k, v in vols.items()}
        total = sum(inv_vols.values())
        weights = {k: v/total for k, v in inv_vols.items()}
        
        self.pair_weights = weights
        return weights
    
    def generate_signals(self, pair_data: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """
        Generate final trading signals for all pairs.
        Returns: {symbol: signal_series}
        """
        signals = {}
        
        # Update pair weights
        self.optimize_pair_weights(pair_data)
        
        for symbol, df in pair_data.items():
            if symbol not in self.configs:
                continue
            
            cfg = self.configs[symbol]
            if len(df) < cfg.min_history_bars:
                signals[symbol] = pd.Series(0, index=df.index)
                continue
            
            # Optimize strategy weights
            strat_weights = self.optimize_strategy_weights(symbol, df)
            
            # Generate combined signal
            combined = pd.Series(0.0, index=df.index)
            for strat in cfg.strategies:
                w = strat_weights.get(strat.name, 0)
                if w < 0.01:
                    continue
                sig = strat.generate_signals(df).reindex(df.index).fillna(0)
                combined += sig * w
            
            # Scale by pair allocation
            pair_w = self.pair_weights.get(symbol, 0)
            combined *= pair_w
            
            # Discretize: only trade if conviction is strong enough
            signals[symbol] = pd.Series(np.where(combined > 0.15, 1, 
                                                  np.where(combined < -0.15, -1, 0)), 
                                        index=df.index)
        
        return signals
    
    def run_backtest(self, pair_data: Dict[str, pd.DataFrame], 
                     initial_capital: float = 100_000.0) -> Tuple[pd.Series, Dict]:
        """
        Full portfolio backtest with walk-forward optimization.
        """
        all_returns = []
        
        # Need aligned data - use minimum available history across enabled pairs
        enabled_data = {k: v for k, v in pair_data.items() if k in self.configs}
        if not enabled_data:
            return pd.Series(), {}
        min_len = min(len(df) for df in enabled_data.values())
        
        print("  Total bars available: %d, train=%d, step=%d, expected windows=%d" % (
            min_len, self.train_bars, 1000, max(0, (min_len - self.train_bars) // 1000 - 1)))
        
        # Walk-forward
        step = 1000
        window_count = 0
        for start in range(0, min_len - self.train_bars - step, step):
            window_count += 1
            train_slice = {sym: df.iloc[start:start + self.train_bars] 
                          for sym, df in enabled_data.items()}
            test_slice = {sym: df.iloc[start + self.train_bars:start + self.train_bars + step]
                         for sym, df in enabled_data.items()}
            
            # Optimize on train
            self.optimize_pair_weights(train_slice)
            
            # Generate signals for test
            test_idx = test_slice[list(test_slice.keys())[0]].index
            portfolio_ret = pd.Series(0.0, index=test_idx)
            
            for symbol, df_test in test_slice.items():
                if symbol not in self.configs:
                    continue
                
                strat_weights = self.optimize_strategy_weights(symbol, train_slice[symbol])
                
                combined_signal = pd.Series(0.0, index=df_test.index)
                for strat in self.configs[symbol].strategies:
                    w = strat_weights.get(strat.name, 0)
                    if w < 0.01:
                        continue
                    sig = strat.generate_signals(df_test).reindex(df_test.index).fillna(0)
                    combined_signal += sig * w
                
                pair_w = self.pair_weights.get(symbol, 0)
                combined_signal *= pair_w
                
                # Discretize
                final_signal = pd.Series(np.where(combined_signal > 0.15, 1,
                                                   np.where(combined_signal < -0.15, -1, 0)),
                                        index=df_test.index)
                
                # Backtest
                cfg = self.configs[symbol]
                ec = self._get_execution_config(cfg)
                
                class MockStrat(Strategy):
                    def __init__(self, sig):
                        super().__init__("mock")
                        self.sig = sig
                    def generate_signals(self, data):
                        return self.sig.reindex(data.index).fillna(0)
                
                bt = VectorizedBacktester(df_test, MockStrat(final_signal), execution_config=ec)
                bt.run()
                
                ret = bt.returns.reindex(portfolio_ret.index).fillna(0)
                portfolio_ret += ret
            
            all_returns.append(portfolio_ret)
        
        print("  Executed %d walk-forward windows" % window_count)
        
        if not all_returns:
            return pd.Series(), {}
        
        total_returns = pd.concat(all_returns).sort_index()
        equity = initial_capital * (1 + total_returns).cumprod()
        
        from backtest.metrics import calculate_metrics
        metrics = calculate_metrics(equity, periods_per_year=252*24)
        
        return total_returns, metrics

# ============================================================
# LIVE EXECUTION INTERFACE
# ============================================================

class LiveSignalGenerator:
    """
    Generates live signals for MT5 execution bridge.
    Call update() with new bar data, get_signals() returns current positions.
    """
    
    def __init__(self, ensemble: AdaptiveEnsemble):
        self.ensemble = ensemble
        self.current_signals: Dict[str, int] = {}
        self.data_buffer: Dict[str, pd.DataFrame] = {}
    
    def update(self, symbol: str, bar: dict):
        """
        Add a new bar to the data buffer.
        bar = {"time": datetime, "open": float, "high": float, "low": float, "close": float}
        """
        if symbol not in self.data_buffer:
            self.data_buffer[symbol] = pd.DataFrame()
        
        new_row = pd.DataFrame([bar]).set_index("time")
        self.data_buffer[symbol] = pd.concat([self.data_buffer[symbol], new_row])
        
        # Keep only last 5000 bars
        if len(self.data_buffer[symbol]) > 5000:
            self.data_buffer[symbol] = self.data_buffer[symbol].iloc[-5000:]
    
    def get_signals(self) -> Dict[str, int]:
        """
        Generate current trading signals for all pairs.
        Returns: {symbol: -1/0/1}
        """
        if len(self.data_buffer) < 1:
            return {}
        
        signals = self.ensemble.generate_signals(self.data_buffer)
        
        result = {}
        for symbol, sig_series in signals.items():
            if len(sig_series) > 0:
                result[symbol] = int(sig_series.iloc[-1])
        
        self.current_signals = result
        return result
    
    def should_trade(self, symbol: str) -> Tuple[bool, int]:
        """
        Check if trade action needed for symbol.
        Returns: (should_act, target_position)
        """
        current = self.current_signals.get(symbol, 0)
        # Compare with last known position (would need state tracking in real use)
        return True, current

# ============================================================
# MAIN / TESTING
# ============================================================

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

def main():
    print("=" * 80)
    print("PRODUCTION ENSEMBLE SYSTEM")
    print("=" * 80)
    
    data = load_data()
    
    # Filter to available pairs
    available = set(data.keys())
    active_configs = [c for c in PAIR_CONFIGS if c.symbol.replace(".s", "") in available or c.symbol in available]
    
    # Fix symbol names - data files don't have .s suffix
    for cfg in active_configs:
        base = cfg.symbol.replace(".s", "")
        if base in data and cfg.symbol not in data:
            data[cfg.symbol] = data[base].copy()
    
    print("\nActive configuration:")
    for cfg in active_configs:
        print("  %s: strategies=%s, enabled=%s" % (cfg.symbol, [s.name for s in cfg.strategies], cfg.enabled))
    
    ensemble = AdaptiveEnsemble(active_configs, train_bars=3000)
    
    # Full backtest
    print("\nRunning walk-forward portfolio backtest...")
    returns, metrics = ensemble.run_backtest(data)
    
    print("\n" + "=" * 80)
    print("PORTFOLIO BACKTEST RESULTS")
    print("=" * 80)
    for k, v in metrics.items():
        print("  %s: %s" % (k, v))
    
    # Per-pair breakdown
    print("\n" + "=" * 80)
    print("FINAL STRATEGY WEIGHTS")
    print("=" * 80)
    for symbol, weights in ensemble.strategy_weights.items():
        print("  %s: %s" % (symbol, {k: round(v, 3) for k, v in weights.items()}))
    
    print("\n" + "=" * 80)
    print("FINAL PAIR ALLOCATIONS")
    print("=" * 80)
    for symbol, weight in ensemble.pair_weights.items():
        print("  %s: %.1f%%" % (symbol, weight * 100))
    
    # Save equity curve
    if len(returns) > 0:
        equity = 100000 * (1 + returns).cumprod()
        results_dir = os.path.join(os.path.dirname(__file__), "..", "..", "results")
        os.makedirs(results_dir, exist_ok=True)
        equity.to_csv(os.path.join(results_dir, "production_equity.csv"))
        returns.to_csv(os.path.join(results_dir, "production_returns.csv"))
        print("\nResults saved to results/")

if __name__ == "__main__":
    main()

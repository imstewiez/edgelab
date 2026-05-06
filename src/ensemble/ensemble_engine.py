"""
Institutional-grade ensemble trading engine.
Orchestrates regime detection, strategy selection, capital allocation, and risk management.
"""
import os
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtest.engine import VectorizedBacktester
from backtest.execution import ExecutionConfig
from backtest.walkforward import WalkForwardAnalysis
from backtest.metrics import calculate_metrics, print_metrics

from ensemble.regime_detector import RegimeDetector
from ensemble.strategy_portfolio import StrategyPortfolio
from ensemble.capital_allocator import CapitalAllocator
from ensemble.risk_manager import RiskManager, RiskLimits
from logger import setup_logger

logger = setup_logger("ensemble_engine")


class EnsembleStrategy:
    """
    Meta-strategy that combines multiple sub-strategies based on regime.
    """
    
    def __init__(
        self,
        portfolio: StrategyPortfolio,
        allocator: CapitalAllocator,
        risk_manager: RiskManager,
        regime_detector: RegimeDetector,
    ):
        self.portfolio = portfolio
        self.allocator = allocator
        self.risk = risk_manager
        self.regime = regime_detector
        self.name = "Ensemble"
        self.current_regime = "UNKNOWN"
        self.active_weights: Dict[str, float] = {}
    
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """
        Generate ensemble signal as weighted combination of active strategies.
        """
        # Detect current regime
        regimes = self.regime.detect(data)
        current_regime = regimes.iloc[-1]
        self.current_regime = current_regime
        
        # Get active strategies for this regime
        active_strategies = self.portfolio.get_active_for_regime(current_regime)
        
        if not active_strategies:
            logger.warning(f"No active strategies for regime {current_regime}")
            return pd.Series(0.0, index=data.index)
        
        # Allocate capital
        weights = self.allocator.allocate(active_strategies)
        self.active_weights = weights
        
        # Generate signals from each strategy and combine
        combined_signal = pd.Series(0.0, index=data.index)
        for rec in active_strategies:
            if rec.name not in weights or weights[rec.name] <= 0:
                continue
            strategy = rec.strategy_factory()
            signal = strategy.generate_signals(data)
            if isinstance(signal, np.ndarray):
                signal = pd.Series(signal, index=data.index)
            signal = signal.fillna(0)
            combined_signal += signal * weights[rec.name]
        
        # Apply risk overlay: vol targeting
        # (simplified: scale combined signal to target vol)
        # In practice, this would use realized portfolio vol
        
        return combined_signal.clip(-1.0, 1.0)


class EnsembleBacktester:
    """
    Walk-forward backtest for the ensemble with regime-aware rebalancing.
    """
    
    def __init__(
        self,
        data: pd.DataFrame,
        portfolio: StrategyPortfolio,
        train_size: int = 3000,
        test_size: int = 1000,
        execution_config: ExecutionConfig = None,
        periods_per_year: int = 365 * 24,
    ):
        self.data = data
        self.portfolio = portfolio
        self.train_size = train_size
        self.test_size = test_size
        self.exec_cfg = execution_config or ExecutionConfig(commission_per_lot=7.0, trade_lots=1.0)
        self.ppy = periods_per_year
        self.regime_detector = RegimeDetector()
        self.allocator = CapitalAllocator()
        self.risk_manager = RiskManager()
    
    def run(self, verbose: bool = True) -> Dict:
        """Run walk-forward ensemble backtest."""
        n = len(self.data)
        all_returns = []
        all_regimes = []
        
        # Generate windows
        windows = []
        start = 0
        while start + self.train_size + self.test_size <= n:
            windows.append((start, start + self.train_size, start + self.train_size, start + self.train_size + self.test_size))
            start += self.test_size
        
        if verbose:
            print(f"Ensemble walk-forward: {len(windows)} windows")
        
        for i, (tr_s, tr_e, te_s, te_e) in enumerate(windows):
            train_data = self.data.iloc[tr_s:tr_e].copy()
            test_data = self.data.iloc[te_s:te_e].copy()
            
            # Train: evaluate all strategies on train window
            for rec in self.portfolio.get_all_strategies():
                try:
                    bt = VectorizedBacktester(
                        train_data, rec.strategy_factory(),
                        execution_config=self.exec_cfg, periods_per_year=self.ppy
                    )
                    m = bt.run()
                    self.portfolio.update_performance(
                        rec.name,
                        m.get("sharpe_ratio", 0),
                        m.get("total_return_pct", 0),
                        m.get("max_drawdown_pct", 0),
                    )
                except Exception as e:
                    logger.warning(f"Train eval failed for {rec.name}: {e}")
            
            # Test: run ensemble on test window
            ensemble = EnsembleStrategy(
                self.portfolio, self.allocator, self.risk_manager, self.regime_detector
            )
            bt = VectorizedBacktester(
                test_data, ensemble,
                execution_config=self.exec_cfg, periods_per_year=self.ppy
            )
            m = bt.run()
            all_returns.append(bt.returns)
            all_regimes.append(ensemble.current_regime)
            
            if verbose:
                print(f"  Window {i+1}: Regime={ensemble.current_regime} | "
                      f"Sharpe={m.get('sharpe_ratio', 0):.3f} | "
                      f"Return={m.get('total_return_pct', 0):.1f}% | "
                      f"DD={m.get('max_drawdown_pct', 0):.1f}% | "
                      f"Weights={ensemble.active_weights}")
        
        # Combine results
        combined_returns = pd.concat(all_returns).sort_index()
        equity = 100_000 * (1 + combined_returns).cumprod()
        metrics = calculate_metrics(equity, periods_per_year=self.ppy)
        
        return {
            "metrics": metrics,
            "equity_curve": equity,
            "returns": combined_returns,
            "regimes": all_regimes,
        }


def build_default_portfolio() -> StrategyPortfolio:
    """Build a starter portfolio with known strategies."""
    portfolio = StrategyPortfolio(min_sharpe_to_trade=0.3, max_dd_to_trade=-35.0)
    
    # MOM100: works in most regimes
    class MOM100:
        name = "MOM100"
        def generate_signals(self, data):
            mom = data["close"].pct_change(100)
            s = pd.Series(0, index=data.index, dtype=float)
            s[mom > 0] = 1
            s[mom < 0] = -1
            return s
    
    # SMA20x100: slower trend following
    class SMA20x100:
        name = "SMA20x100"
        def generate_signals(self, data):
            s = pd.Series(0, index=data.index, dtype=float)
            s[data["close"].rolling(20).mean() > data["close"].rolling(100).mean()] = 1
            s[data["close"].rolling(20).mean() < data["close"].rolling(100).mean()] = -1
            return s
    
    # Range mean reversion (only for ranging regimes)
    class RangeMR:
        name = "RangeMR"
        def generate_signals(self, data):
            hh = data["high"].rolling(20).max()
            ll = data["low"].rolling(20).min()
            mid = (hh + ll) / 2
            s = pd.Series(0, index=data.index, dtype=float)
            s[data["close"] < mid * 0.995] = 1
            s[data["close"] > mid * 1.005] = -1
            return s
    
    # Vol breakout (only for volatile regimes)
    class VolBreakout:
        name = "VolBreakout"
        def generate_signals(self, data):
            atr = (data["high"] - data["low"]).rolling(20).mean()
            atr_pct = atr / data["close"]
            high_vol = atr_pct > atr_pct.rolling(50).mean() * 1.3
            hh = data["high"].rolling(10).max().shift(1)
            ll = data["low"].rolling(10).min().shift(1)
            s = pd.Series(0, index=data.index, dtype=float)
            s[high_vol & (data["close"] > hh)] = 1
            s[high_vol & (data["close"] < ll)] = -1
            return s
    
    portfolio.add_strategy("MOM100", MOM100, ["TRENDING_UP", "TRENDING_DOWN", "RANGING", "ALL"])
    portfolio.add_strategy("SMA20x100", SMA20x100, ["TRENDING_UP", "TRENDING_DOWN", "ALL"])
    portfolio.add_strategy("RangeMR", RangeMR, ["RANGING"])
    portfolio.add_strategy("VolBreakout", VolBreakout, ["VOLATILE"])
    
    return portfolio


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="H1")
    args = parser.parse_args()
    
    df = pd.read_parquet(f"data/raw/{args.symbol}_{args.timeframe}.parquet")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    
    print(f"Loaded {len(df)} bars")
    print("=" * 80)
    print("ENSEMBLE ENGINE BACKTEST")
    print("=" * 80)
    
    portfolio = build_default_portfolio()
    backtester = EnsembleBacktester(df, portfolio)
    result = backtester.run(verbose=True)
    
    print("\n" + "=" * 80)
    print("ENSEMBLE RESULTS")
    print("=" * 80)
    print_metrics(result["metrics"])
    
    # Compare to base MOM100
    print("\n" + "=" * 80)
    print("BASE MOM100 (for comparison)")
    print("=" * 80)
    class MOM100:
        name = "MOM100"
        def generate_signals(self, data):
            mom = data["close"].pct_change(100)
            s = pd.Series(0, index=data.index, dtype=float)
            s[mom > 0] = 1
            s[mom < 0] = -1
            return s
    
    wfa = WalkForwardAnalysis(df, lambda: MOM100(), train_size=3000, test_size=1000,
                              execution_config=ExecutionConfig(commission_per_lot=7.0, trade_lots=1.0),
                              periods_per_year=365*24)
    base = wfa.run(verbose=False)
    print_metrics(base)


if __name__ == "__main__":
    main()

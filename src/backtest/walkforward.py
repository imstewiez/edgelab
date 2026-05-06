"""
Walk-forward analysis framework.
Prevents overfitting by training on in-sample data and testing on out-of-sample data.
"""
from typing import Dict, List, Optional, Callable

import pandas as pd
import numpy as np

from .engine import VectorizedBacktester
from .metrics import calculate_metrics, print_metrics


class WalkForwardAnalysis:
    """
    Walk-forward analysis with rolling or expanding windows.
    
    For each window:
    1. Train period: optimize strategy parameters (optional)
    2. Test period: run backtest with trained parameters
    3. Record out-of-sample performance
    
    Finally, combine all out-of-sample periods into a continuous equity curve.
    """
    
    def __init__(
        self,
        data: pd.DataFrame,
        strategy_factory: Callable,  # Function that returns a strategy instance
        train_size: int,             # Number of bars in training window
        test_size: int,              # Number of bars in test window
        step_size: Optional[int] = None,  # Step between windows; defaults to test_size
        window_type: str = "rolling",  # "rolling" or "expanding"
        execution_config=None,
        periods_per_year: int = 252 * 24
    ):
        self.data = data
        self.strategy_factory = strategy_factory
        self.train_size = train_size
        self.test_size = test_size
        self.step_size = step_size or test_size
        self.window_type = window_type
        self.execution_config = execution_config
        self.periods_per_year = periods_per_year
        
        self.results: List[Dict] = []
        self.combined_metrics: Optional[Dict] = None
    
    def run(self, verbose: bool = True) -> Dict:
        """
        Run walk-forward analysis across all windows.
        Returns combined out-of-sample metrics.
        """
        n_bars = len(self.data)
        windows = []
        
        # Generate window boundaries
        start = 0
        while start + self.train_size + self.test_size <= n_bars:
            train_start = start
            train_end = start + self.train_size
            test_start = train_end
            test_end = train_end + self.test_size
            
            windows.append((train_start, train_end, test_start, test_end))
            start += self.step_size
        
        if not windows:
            raise ValueError(
                f"Data too short for walk-forward. "
                f"Need {self.train_size + self.test_size} bars, have {n_bars}"
            )
        
        if verbose:
            print(f"Walk-forward: {len(windows)} windows | "
                  f"Train: {self.train_size} bars | Test: {self.test_size} bars")
        
        all_test_returns = []
        
        for i, (tr_s, tr_e, te_s, te_e) in enumerate(windows):
            train_data = self.data.iloc[tr_s:tr_e]
            test_data = self.data.iloc[te_s:te_e]
            
            # For now, we use the same strategy on both train and test
            # In a real optimization loop, you'd grid-search parameters on train_data
            # and pick the best, then apply to test_data.
            # This simplified version assumes the strategy is already parameterized.
            strategy = self.strategy_factory()
            
            # Run on test data
            bt = VectorizedBacktester(
                test_data,
                strategy,
                execution_config=self.execution_config,
                periods_per_year=self.periods_per_year
            )
            metrics = bt.run()
            
            result = {
                "window": i,
                "train_start": train_data.index[0],
                "train_end": train_data.index[-1],
                "test_start": test_data.index[0],
                "test_end": test_data.index[-1],
                "metrics": metrics,
                "equity_curve": bt.equity_curve,
                "returns": bt.returns,
                "trades": bt.trades,
            }
            self.results.append(result)
            all_test_returns.append(bt.returns)
            
            if verbose:
                print(f"  Window {i+1}/{len(windows)}: "
                      f"Return={metrics.get('total_return_pct', 0):.2f}% | "
                      f"Sharpe={metrics.get('sharpe_ratio', 0):.3f} | "
                      f"MaxDD={metrics.get('max_drawdown_pct', 0):.2f}%")
        
        # Combine all out-of-sample returns into continuous equity curve
        self.combined_metrics = self._combine_results(all_test_returns)
        
        if verbose:
            print("\nCombined Out-of-Sample Performance:")
            print_metrics(self.combined_metrics)
        
        return self.combined_metrics
    
    def _combine_results(self, returns_list: List[pd.Series]) -> Dict:
        """Combine returns from all test windows into single metrics."""
        if not returns_list:
            return {"error": "No results"}
        
        combined_returns = pd.concat(returns_list)
        combined_returns = combined_returns.sort_index()
        
        # Build equity curve from combined returns
        equity = 100_000 * (1 + combined_returns).cumprod()
        
        return calculate_metrics(equity, periods_per_year=self.periods_per_year)
    
    def get_window_summary(self) -> pd.DataFrame:
        """Return summary of all windows as a DataFrame."""
        rows = []
        for r in self.results:
            m = r["metrics"]
            rows.append({
                "window": r["window"],
                "test_start": r["test_start"],
                "test_end": r["test_end"],
                "total_return_pct": m.get("total_return_pct"),
                "sharpe_ratio": m.get("sharpe_ratio"),
                "max_drawdown_pct": m.get("max_drawdown_pct"),
                "num_trades": m.get("num_trades", 0),
                "win_rate_pct": m.get("win_rate_pct", 0),
            })
        return pd.DataFrame(rows)

"""
Strategy portfolio: collection of strategies with performance tracking.
Each strategy has a 'fitness score' based on recent walk-forward performance.
"""
from typing import Dict, List, Callable, Optional
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import numpy as np


@dataclass
class StrategyRecord:
    name: str
    strategy_factory: Callable
    regimes: List[str]  # Which regimes this strategy is designed for
    sharpe_history: List[float]
    return_history: List[float]
    max_dd_history: List[float]
    weight: float = 0.0
    active: bool = True
    
    @property
    def avg_sharpe(self) -> float:
        if not self.sharpe_history:
            return 0.0
        # Exponential weighting: recent windows matter more
        weights = np.exp(np.linspace(-1, 0, len(self.sharpe_history)))
        weights /= weights.sum()
        return float(np.average(self.sharpe_history, weights=weights))
    
    @property
    def avg_max_dd(self) -> float:
        if not self.max_dd_history:
            return -999.0
        return float(np.mean(self.max_dd_history))


class StrategyPortfolio:
    """
    Manages a collection of strategies.
    Tracks performance and assigns weights.
    """
    
    def __init__(self, min_sharpe_to_trade: float = 0.3, max_dd_to_trade: float = -30.0):
        self.strategies: Dict[str, StrategyRecord] = {}
        self.min_sharpe = min_sharpe_to_trade
        self.max_dd = max_dd_to_trade
    
    def add_strategy(self, name: str, factory: Callable, regimes: List[str]):
        self.strategies[name] = StrategyRecord(
            name=name,
            strategy_factory=factory,
            regimes=regimes,
            sharpe_history=[],
            return_history=[],
            max_dd_history=[],
        )
    
    def update_performance(self, name: str, sharpe: float, ret: float, max_dd: float):
        if name not in self.strategies:
            return
        rec = self.strategies[name]
        rec.sharpe_history.append(sharpe)
        rec.return_history.append(ret)
        rec.max_dd_history.append(max_dd)
        # Keep last 20 windows
        rec.sharpe_history = rec.sharpe_history[-20:]
        rec.return_history = rec.return_history[-20:]
        rec.max_dd_history = rec.max_dd_history[-20:]
    
    def get_active_for_regime(self, regime: str) -> List[StrategyRecord]:
        """Get strategies that are active and suitable for current regime."""
        active = []
        for rec in self.strategies.values():
            if not rec.active:
                continue
            if regime not in rec.regimes and "ALL" not in rec.regimes:
                continue
            if rec.avg_sharpe < self.min_sharpe:
                continue
            if rec.avg_max_dd < self.max_dd:
                continue
            active.append(rec)
        return active
    
    def get_all_strategies(self) -> List[StrategyRecord]:
        return list(self.strategies.values())

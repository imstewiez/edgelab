"""Kelly Criterion position sizing module.

Calculates optimal position size based on historical win rate and payoff ratio.
Uses fractional Kelly (0.25x) for conservative sizing on retail accounts.
"""
import numpy as np
import pandas as pd
from typing import List, Optional


class KellySizer:
    """Fractional Kelly Criterion position sizing.
    
    Formula: f* = (p * b - q) / b
    where: p = win probability, q = loss probability (1-p)
           b = avg win / avg loss (payoff ratio)
    
    We use 0.25x full Kelly (quarter Kelly) for safety.
    """
    
    DEFAULT_FRACTION = 0.25
    MAX_KELLY = 0.10  # Cap at 10% of equity per trade
    MIN_KELLY = 0.01  # Minimum 1% of equity
    
    def __init__(self, trade_history: Optional[List[dict]] = None):
        self.trade_history = trade_history or []
        self._win_rate = None
        self._payoff_ratio = None
        self._kelly_fraction = None
    
    def add_trade(self, pnl: float):
        """Record a completed trade P&L for Kelly calculation."""
        self.trade_history.append({"pnl": pnl})
        self._invalidate_cache()
    
    def _invalidate_cache(self):
        self._win_rate = None
        self._payoff_ratio = None
        self._kelly_fraction = None
    
    def calculate(self, min_trades: int = 20) -> float:
        """Calculate fractional Kelly position size.
        
        Returns fraction of equity to risk (0.01 = 1%).
        """
        if len(self.trade_history) < min_trades:
            # Default: use fixed 2% until enough history
            return 0.02
        
        pnls = np.array([t["pnl"] for t in self.trade_history])
        wins = pnls[pnls > 0]
        losses = pnls[pnls <= 0]
        
        if len(wins) == 0 or len(losses) == 0:
            return 0.02
        
        p = len(wins) / len(pnls)  # Win probability
        q = 1.0 - p
        
        avg_win = np.mean(wins)
        avg_loss = abs(np.mean(losses))
        
        if avg_loss == 0:
            return self.MAX_KELLY
        
        b = avg_win / avg_loss  # Payoff ratio
        
        if b <= 0:
            return self.MIN_KELLY
        
        # Full Kelly
        full_kelly = (p * b - q) / b
        
        # Quarter Kelly (conservative)
        fractional = full_kelly * self.DEFAULT_FRACTION
        
        # Clamp to safe range
        kelly = max(self.MIN_KELLY, min(self.MAX_KELLY, fractional))
        
        self._win_rate = p
        self._payoff_ratio = b
        self._kelly_fraction = kelly
        
        return kelly
    
    def get_diagnostics(self) -> dict:
        """Return Kelly calculation details."""
        if self._kelly_fraction is None:
            self.calculate()
        return {
            "win_rate": self._win_rate,
            "payoff_ratio": self._payoff_ratio,
            "full_kelly": self._kelly_fraction / self.DEFAULT_FRACTION if self._kelly_fraction else None,
            "fractional_kelly": self._kelly_fraction,
            "trade_count": len(self.trade_history),
        }


def kelly_lot_size(equity: float, kelly_fraction: float, sl_distance: float, point_value: float) -> float:
    """Convert Kelly equity fraction to lot size.
    
    Args:
        equity: Account equity
        kelly_fraction: Fraction of equity to risk (e.g., 0.02 = 2%)
        sl_distance: Stop loss distance in price terms
        point_value: Dollar value per point for the asset
        
    Returns:
        Lot size
    """
    if sl_distance <= 0 or point_value <= 0:
        return 0.01
    
    risk_amount = equity * kelly_fraction
    lots = risk_amount / (sl_distance * point_value)
    
    # Clamp to reasonable range
    return max(0.01, min(1.0, lots))

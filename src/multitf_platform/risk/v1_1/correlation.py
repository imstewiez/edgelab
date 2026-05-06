"""Portfolio correlation risk checker.

Prevents opening positions that would increase portfolio correlation
beyond a safe threshold. Uses recent H1 returns to compute correlations.
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional


class CorrelationRiskChecker:
    """Check portfolio correlation before opening new positions.
    
    If adding a new position would push portfolio correlation above
    the threshold, reduce size or block the trade.
    """
    
    DEFAULT_THRESHOLD = 0.50
    LOOKBACK_BARS = 50  # Use last 50 H1 bars for correlation
    
    def __init__(self, threshold: float = DEFAULT_THRESHOLD):
        self.threshold = threshold
        self.price_history: Dict[str, pd.Series] = {}
    
    def update_price(self, symbol: str, price: float, timestamp: pd.Timestamp):
        """Record latest price for correlation calculation."""
        if symbol not in self.price_history:
            self.price_history[symbol] = pd.Series(dtype=float)
        self.price_history[symbol][timestamp] = price
        
        # Keep only recent bars
        if len(self.price_history[symbol]) > self.LOOKBACK_BARS:
            self.price_history[symbol] = self.price_history[symbol].iloc[-self.LOOKBACK_BARS:]
    
    def _get_returns(self, symbol: str) -> pd.Series:
        """Get return series for a symbol."""
        if symbol not in self.price_history or len(self.price_history[symbol]) < 10:
            return pd.Series(dtype=float)
        return self.price_history[symbol].pct_change().dropna()
    
    def check_correlation(self, new_symbol: str, new_direction: int, 
                          existing_positions: Dict[str, int]) -> dict:
        """Check if adding a new position would violate correlation threshold.
        
        Args:
            new_symbol: Symbol being considered
            new_direction: Direction of new trade (1=long, -1=short)
            existing_positions: Dict of symbol -> direction for current positions
            
        Returns:
            Dict with 'allowed', 'scale', 'reason', 'max_correlation'
        """
        # No existing positions = no correlation risk
        if not existing_positions:
            return {"allowed": True, "scale": 1.0, "reason": "", "max_correlation": 0.0}
        
        new_returns = self._get_returns(new_symbol)
        if len(new_returns) < 10:
            return {"allowed": True, "scale": 1.0, "reason": "Insufficient data", "max_correlation": 0.0}
        
        correlations = []
        for sym, direction in existing_positions.items():
            existing_returns = self._get_returns(sym)
            if len(existing_returns) < 10:
                continue
            
            # Align series
            combined = pd.DataFrame({"new": new_returns, "existing": existing_returns}).dropna()
            if len(combined) < 10:
                continue
            
            # Adjust for direction (short positions invert correlation)
            adj_existing = combined["existing"] * direction
            adj_new = combined["new"] * new_direction
            
            corr = np.corrcoef(adj_new, adj_existing)[0, 1]
            if not np.isnan(corr):
                correlations.append(abs(corr))
        
        if not correlations:
            return {"allowed": True, "scale": 1.0, "reason": "No correlation data", "max_correlation": 0.0}
        
        max_corr = max(correlations)
        
        if max_corr >= self.threshold:
            # Scale down proportionally
            scale = max(0.0, 1.0 - (max_corr - self.threshold) / (1.0 - self.threshold))
            return {
                "allowed": scale > 0,
                "scale": scale,
                "reason": f"Correlation {max_corr:.2f} >= threshold {self.threshold:.2f}",
                "max_correlation": max_corr,
            }
        
        return {
            "allowed": True,
            "scale": 1.0,
            "reason": f"Correlation {max_corr:.2f} < threshold",
            "max_correlation": max_corr,
        }
